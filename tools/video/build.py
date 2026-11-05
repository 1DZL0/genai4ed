"""Edit the recorded lesson into a short, presentation-ready video: a title, the teacher writing
the lesson, a few seconds of both screens side by side, then the student's conversation on its
own, then the teacher's screen showing what that conversation produced (the alert, the note
the teacher sent, the summary), then a close. One device at a time on a light paper stage
with a slowly drifting dot grid (the teacher's laptop, the student's tablet), headlines
above it in the product's own fonts, slow zooms onto the part that matters. Where the teacher
reads down a card, the scroll is not the filmed one (twelve frames a second make a staircase)
but a glide at full frame rate over the tall capture the recorder took at that mark.

From the repo root, after tools/video/record.py:

    python tools/video/build.py [--tempo 1.2] [--name genai4ed-research-meeting]

Writes <name>.mp4 (with headlines) and <name>-no-captions.mp4 (chapter cards and screen
labels only, for talking over) to Downloads. The scenes, headlines and zooms are the SCENES
list below; every time in it is a mark the recorder wrote, plus or minus seconds."""

import argparse
import bisect
import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / ".superdesign" / "tmp" / "video-2026-10-26"
# ffmpeg from the PATH (brew install ffmpeg on a Mac); the Winget build on the Windows box.
FFMPEG = shutil.which("ffmpeg") or (
    r"C:\Users\diese\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe"
)
OUT_DIR = Path.home() / "Downloads"

W, H, FPS = 1920, 1080, 30
# The platform's own colours: paper, ink, pencil, and the blue wash for the chapter pill.
PAPER, INK, PENCIL, DOTS = "#f5f7fa", "#1f2a44", "#5c6577", "#d3dbe5"
PILL_BG, PILL_TEXT, BASE, BASE_EDGE = "#e8eff9", "#2457a5", "#d4dbe4", "#b9c4d1"
FADE = 12  # frames of crossfade between scenes
MOVE = 27  # frames a zoom takes
TEXT_FADE = 9

# ---------- the edit ----------

TITLE = ("GenAI4ED", "A class agent that teaches inside the teacher's rules", "")
CLOSE = ("GenAI4ED", "Teacher-governed AI for the classroom", "A research project in progress")

# A camera is (x, y, width) in the screen's own pixels at 1440 by 900; the height follows the
# 16:10 frame. "full" is the whole screen.
FULL = (0, 0, 1440)

SCENES = [
    {"card": TITLE, "seconds": 3.2},
    {"chapter": (1, "The teacher writes the lesson"), "seconds": 1.6},
    {
        "screen": "teacher", "chapter": 1,
        "from": "begin", "to": "card_scroll",
        "cameras": [("begin", "compose"), ("lesson_reply-0.5", "card"), ("rules_typing-0.4", "chat_low"),
                    ("rules_reply-0.3", "card")],
        "headlines": [
            ("begin", "The teacher describes the lesson in their own words."),
            ("lesson_reply", "The agent drafts it: steps, questions, what counts as done."),
            ("rules_typing", "The teacher sets the rules: hints yes, the answer never."),
        ],
    },
    # The card read top to bottom, then back: a glide over the tall capture. Keys are (second,
    # how far the pane has scrolled, as a fraction of its length); it rests at each and eases
    # between them, so a short card and a long one are both read at the same unhurried pace.
    {
        "glide": "card_scroll", "screen": "teacher", "chapter": 1, "camera": "pane",
        "keys": [(0.0, 0), (2.6, 0.5), (3.9, 0.5), (6.6, "end"), (8.0, "end"), (9.6, 0)],
        "headlines": [(0.0, "Every step and every rule, read back on one card.")],
    },
    {
        "screen": "teacher", "chapter": 1,
        "from": "approve-0.9", "to": "start",
        # Open level with where the glide rested (the pane camera) and ease to the Approve row,
        # so the cut into this scene does not jump.
        "cameras": [("approve-0.9", "pane"), ("approve-0.6", "card_top")],
        "headlines": [("approve-0.9", "Nothing reaches a student until the teacher approves it.")],
    },
    {
        "split": True, "chapter": 0,
        "from": "start", "to": "opening+3",
        "headlines": [("start", "One lesson, two screens: the teacher's and a student's.")],
    },
    {"chapter": (2, "A student works with the tutor"), "seconds": 1.6},
    # The conversation at its own pace: this is the part people should be able to read.
    {
        "screen": "student", "chapter": 2, "tempo": 1.0,
        "from": "opening-0.5", "to": "near_reply+4.5",
        "cameras": [("opening-0.5", "student_full"), ("opening+1.5", "student_talk")],
        "headlines": [
            ("opening-0.5", "Each student has the tutor to themselves."),
            ("warm_typing", "A first question, answered in their own words."),
            ("slip_typing", "A wrong turn. The tutor asks, it doesn't tell."),
            ("example_press", "Stuck? One press. An example, never the answer."),
            ("near_typing", "Closer now. Still theirs to finish."),
            ("near_reply+1.5", "Three tries in, the teacher is told. Quietly."),
        ],
    },
    {
        "screen": "student", "chapter": 2, "tempo": 1.0,
        "from": "note_arrived-1.5", "to": "got_reply+4.5",
        "cameras": [("note_arrived-1.5", "student_talk")],
        "headlines": [
            ("note_arrived-1.5", "The teacher's note arrives, through the tutor."),
            ("got_typing", "And they get there, in their own working."),
        ],
    },
    {"chapter": (3, "What the teacher sees"), "seconds": 1.6},
    {
        "screen": "teacher", "chapter": 3,
        "from": "board_struggling-0.5", "to": "note_reply+2.5",
        "cameras": [("board_struggling-0.5", "full"), ("board_struggling+0.8", "alerts"),
                    ("note_typing", "chat_low")],
        "headlines": [
            ("board_struggling-0.5", "Meanwhile, the teacher sees the whole class."),
            ("board_struggling+1.5", "Struggling students are flagged, with the reason why."),
            ("note_typing", "One sentence from the teacher, passed on by the agent."),
        ],
    },
    {
        "screen": "teacher", "chapter": 3,
        "from": "summary-0.5", "to": "summary_scroll",
        "cameras": [("summary-0.5", "summary")],
        "headlines": [("summary-0.5", "When the lesson ends: how the class did, and a note on each student.")],
    },
    {
        "glide": "summary_scroll", "screen": "teacher", "chapter": 3, "camera": "pane",
        "keys": [(0.0, 0), (5.2, "end"), (7.4, "end")],
        "headlines": [(0.0, "Nothing reaches a student until the teacher confirms it.")],
    },
    {"card": CLOSE, "seconds": 3.6},
]

# Named cameras, set from the recorded frames: where each part sits on the 1440 by 900 screen.
CAMERAS = {
    "full": FULL,
    "compose": (330, 150, 1100),  # the empty thread: the heading and the box the teacher types in
    "card": (560, 40, 880),  # the lesson card: title, what to check, what was decided, Approve
    # The card scrolled: the step rows and the help pills. Set low: in the 26 October take the
    # scroll ran on into the whole page, and the capture left a blank band at the top.
    "card_scroll": (560, 300, 880),
    "card_top": (560, 120, 880),  # what was decided, and the Approve and Start row
    "alerts": (540, 150, 900),  # the class board: who needs the teacher, and why
    "chat_low": (100, 338, 900),  # the teacher's chat: the note typed and the agent's answer
    "summary": (540, 30, 900),  # the end of the lesson: how the class did
    "summary_notes": (540, 60, 900),  # a note on each student, each to confirm
    "student_full": FULL,
    "student_talk": (220, 275, 1000),  # the latest turns, the help buttons and the box
    "pane": (712, 44, 728),  # the card pane on its own, for a glide down it (not the chat beside it)
}

# ---------- fonts ----------


def _first_font(candidates: list[str]) -> str:
    """The first font file that exists, so a render runs on Windows, a Mac or Linux alike."""
    for path in candidates:
        if Path(path).exists():
            return path
    return candidates[-1]


def product_fonts() -> tuple[str, str]:
    """The product's own Latin fonts, from the frontend's build: Atkinson Hyperlegible Next and
    Literata. A clean system sans and serif stand in if the build cache is not there (it is
    gitignored, so on a fresh machine the headlines use the stand-in; the app UI in the frames
    is unaffected)."""
    media = ROOT / "frontend" / ".next" / "dev" / "static"
    found = {}
    for css in (media / "chunks").glob("*single.css"):
        family = "atkinson" if "atkinson" in css.name else "literata" if "literata" in css.name else None
        if not family:
            continue
        for url, rng in re.findall(r'url\("\.\./media/([^"]+)"\)[^}]*?unicode-range:\s*([^;]+);', css.read_text(encoding="utf-8")):
            if rng.startswith("U+0000-00FF") or rng.startswith("U+??"):
                found[family] = str(media / "media" / url)
    sans = found.get("atkinson") or _first_font([
        r"C:\Windows\Fonts\segoeui.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ])
    serif = found.get("literata") or _first_font([
        r"C:\Windows\Fonts\georgia.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/System/Library/Fonts/Times.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ])
    return sans, serif


SANS, SERIF = product_fonts()


@lru_cache(maxsize=32)
def font(path: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_axes([weight])
    except (OSError, AttributeError):
        pass
    return f


def wrap(text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if f.getlength(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line]


# ---------- the recording ----------

timeline = json.loads((HERE / "timeline.json").read_text(encoding="utf-8"))
SRC_W, SRC_H = timeline["view"]["width"], timeline["view"]["height"]
# Read from a frame rather than trusted from the recorder: an older take filmed with the
# browser's screencast has frames at screen size whatever was asked for.
SCALE = Image.open(HERE / "frames" / "teacher" / timeline["teacher"][0]["file"]).size[0] / SRC_W
MARKS: dict[str, float] = {}
for m in timeline["marks"]:
    if "mark" in m:
        MARKS.setdefault(m["mark"], m["t"])
SPEEDS = sorted((m["t"], m["speed"]) for m in timeline["marks"] if "speed" in m)
SPEED_T = [t for t, _ in SPEEDS]
FRAMES = {name: sorted(timeline[name], key=lambda f: f["t"]) for name in ("teacher", "student")}
FRAME_T = {name: [f["t"] for f in frames] for name, frames in FRAMES.items()}


def when(moment: str) -> float:
    """A mark's wall-clock time, with an optional +n or -n seconds."""
    name, sign, offset = re.fullmatch(r"([a-z0-9_]+)(?:([+-])([\d.]+))?", moment).groups()
    t = MARKS[name]
    return t + (float(offset) if sign == "+" else -float(offset) if sign == "-" else 0.0)


def speed_at(t: float) -> float:
    i = bisect.bisect_right(SPEED_T, t) - 1
    return SPEEDS[i][1] if i >= 0 else 1.0


def frame_at(screen: str, t: float) -> str:
    i = max(bisect.bisect_right(FRAME_T[screen], t) - 1, 0)
    return FRAMES[screen][i]["file"]


def _small_change(a: Image.Image, b: Image.Image) -> bool:
    """True when two neighbouring captures differ only a little. Blending a little motion
    (a caret, a word typed) smooths it; blending across a jump (the page scrolling to a new
    message) cross-dissolves two different pictures into a ghost, which reads as a glitch."""
    diff = ImageChops.difference(a.resize((48, 30)), b.resize((48, 30)))
    return sum(ImageStat.Stat(diff).mean) / 3 < 16  # mean channel difference, 0 to 255


def smooth(screen: str, t: float, rect: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    """The screen at moment t, blended towards the next captured frame only when the two are
    close in time and in content, so gentle motion is smooth but a scroll jump cuts cleanly
    instead of ghosting."""
    times, frames = FRAME_T[screen], FRAMES[screen]
    i = max(bisect.bisect_right(times, t) - 1, 0)
    here = view(screen, frames[i]["file"], rect, size)
    if i + 1 < len(frames):
        gap = times[i + 1] - times[i]
        u = (t - times[i]) / gap if gap > 0 else 0.0
        if gap < 0.3 and 0.08 < u < 0.92:
            nxt = view(screen, frames[i + 1]["file"], rect, size)
            if _small_change(here, nxt):
                return Image.blend(here, nxt, u)
            return here if u < 0.5 else nxt  # a jump: hold the nearer frame, no ghost
    return here


@lru_cache(maxsize=6)
def source(screen: str, file: str) -> Image.Image:
    return Image.open(HERE / "frames" / screen / file).convert("RGB")


@lru_cache(maxsize=16)
def view(screen: str, file: str, rect: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    return crop_view(source(screen, file), rect, size)


def crop_view(img: Image.Image, rect: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    """The camera's rectangle of a captured screen, resized to the frame."""
    x, y, w = rect
    h = w * size[1] / size[0]
    box = [x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE]
    out = img.crop(tuple(round(v) for v in box)).resize(size, Image.LANCZOS, reducing_gap=2.0)
    if size[0] > (box[2] - box[0]) * 1.05:  # enlarged: a light sharpen keeps the text crisp
        out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=70, threshold=2))
    else:  # reduced from the double-density capture: a touch of sharpening restores the edges
        out = out.filter(ImageFilter.UnsharpMask(radius=0.8, percent=40, threshold=1))
    return out


# ---------- the tall captures ----------

TALL = timeline.get("tall", {})


@lru_cache(maxsize=4)
def tall_capture(name: str) -> tuple[Image.Image, Image.Image, dict]:
    """What the recorder took at a scroll mark: the screen as it stood, the pane's whole content
    as one tall image, and where the pane sits on the screen (box, heading height, total)."""
    t = TALL[name]
    base = Image.open(HERE / "tall" / t["base"]).convert("RGB")
    image = Image.open(HERE / "tall" / t["image"]).convert("RGB")
    return base, image, t


@lru_cache(maxsize=4)
def content_bottom(name: str) -> float:
    """Where the card's content actually ends in the tall image, in its own CSS pixels. The
    pane's scroll height can run on past the last line with empty space, so a glide must stop
    at the real bottom, not scroll into white. A row counts as ink when a small fraction of it
    is dark, so a short last line (a name, a lone bullet) still registers."""
    _, image, _ = tall_capture(name)
    column = image.convert("L").resize((200, image.height), Image.BILINEAR)
    ink = [any(column.getpixel((c, row)) < 220 for c in range(0, 200, 3)) for row in range(image.height)]
    for row in range(image.height - 1, -1, -1):
        if ink[row]:
            return row / SCALE
    return image.height / SCALE


def glided(name: str, top: float) -> Image.Image:
    """The screen with its pane scrolled down by top pixels, composed from the tall capture.
    The pane's own heading stays put, as the real one does."""
    base, image, t = tall_capture(name)
    x, y, w, h = t["box"]
    header = t["header"]
    top = min(max(top, 0.0), t["total"] - h)
    strip = image.crop((0, round((top + header) * SCALE), round(w * SCALE), round((top + h) * SCALE)))
    out = base.copy()
    out.paste(strip, (round(x * SCALE), round((y + header) * SCALE)))
    return out


def scrolled_to(keys: list, t: float, most: float) -> float:
    """How far the pane has scrolled at second t of a glide: it rests at each key and eases
    between them. A key is "end" (as far as the pane goes), a fraction of that between 0 and 1,
    or a pixel count; cards differ in length, so fractions travel the same share of each."""
    def px(value):
        if value == "end":
            return most
        value = float(value)
        return value * most if 0 < value < 1 else min(value, most)

    points = [(sec, px(value)) for sec, value in keys]
    if t <= points[0][0]:
        return points[0][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:], strict=False):
        if t <= t1:
            return v0 + (v1 - v0) * ease((t - t0) / (t1 - t0)) if t1 > t0 else v1
    return points[-1][1]


def clamp(rect: tuple[float, float, float]) -> tuple[int, int, int]:
    x, y, w = rect
    w = min(w, SRC_W)
    h = w * 10 / 16
    x = min(max(x, 0), SRC_W - w)
    y = min(max(y, 0), SRC_H - h)
    return (round(x), round(y), round(w))


# ---------- drawing ----------

CONTENT = (1280, 800)  # one screen, 16:10
SPLIT = (760, 475)  # each screen when both are shown
GRID = 34  # dot spacing on the stage
DEVICE_TOP = 196


@lru_cache(maxsize=1)
def dot_grid() -> Image.Image:
    img = Image.new("RGB", (W + GRID, H + GRID), PAPER)
    d = ImageDraw.Draw(img)
    for y in range(0, H + GRID, GRID):
        for x in range(0, W + GRID, GRID):
            d.ellipse((x - 1.6, y - 1.6, x + 1.6, y + 1.6), fill=DOTS)
    return img


_tick = [0]


def stage() -> Image.Image:
    """Paper with a dot grid that drifts a little every frame, so even a still screen breathes."""
    _tick[0] += 1
    k = _tick[0]
    dx, dy = (k * 0.30) % GRID, (k * 0.18) % GRID
    return dot_grid().crop((round(dx), round(dy), round(dx) + W, round(dy) + H))


@lru_cache(maxsize=8)
def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


@lru_cache(maxsize=8)
def device_shell(kind: str, size: tuple[int, int]) -> tuple[Image.Image, tuple[int, int]]:
    """A laptop or a tablet drawn around a screen of this size: the shell as RGBA, and where the
    screen sits inside it."""
    cw, ch = size
    if kind == "laptop":
        bezel, radius = max(12, cw // 90), max(18, cw // 55)
        base_h, base_extra = max(14, cw // 70), max(50, cw // 12)
        w, h = cw + 2 * bezel + 2 * base_extra, ch + 2 * bezel + base_h
        shell = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(shell)
        d.rounded_rectangle((base_extra, 0, base_extra + cw + 2 * bezel - 1, ch + 2 * bezel), radius, fill=INK)
        d.ellipse((w // 2 - 3, bezel // 2 - 3, w // 2 + 3, bezel // 2 + 3), fill="#3a4766")
        top = ch + 2 * bezel - 2
        d.rounded_rectangle((0, top, w - 1, top + base_h), base_h // 2, fill=BASE)
        d.line((base_h // 2, top + 1, w - base_h // 2, top + 1), fill=BASE_EDGE, width=2)
        notch = max(90, cw // 9)
        d.rounded_rectangle((w // 2 - notch // 2, top, w // 2 + notch // 2, top + base_h // 3), 4, fill=BASE_EDGE)
        return shell, (base_extra + bezel, bezel)
    bezel, radius = max(16, cw // 60), max(26, cw // 34)
    w, h = cw + 2 * bezel, ch + 2 * bezel
    shell = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(shell)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=INK)
    d.ellipse((w // 2 - 3, bezel // 2 - 3, w // 2 + 3, bezel // 2 + 3), fill="#3a4766")
    return shell, (bezel, bezel)


@lru_cache(maxsize=8)
def device_shadow(kind: str, size: tuple[int, int]) -> Image.Image:
    shell, _ = device_shell(kind, size)
    pad = 60
    alpha = Image.new("L", (shell.width + 2 * pad, shell.height + 2 * pad), 0)
    alpha.paste(shell.getchannel("A").point(lambda a: 52 if a else 0), (pad, pad))
    alpha = alpha.filter(ImageFilter.GaussianBlur(26))
    shadow = Image.new("RGBA", alpha.size, (31, 42, 68, 0))
    shadow.putalpha(alpha)
    return shadow


def place(canvas: Image.Image, content: Image.Image, kind: str, cx: int, top: int) -> tuple[int, int]:
    """A device with this screen in it, centred on cx, its top at top. Returns its bottom and
    width, for a label under it."""
    shell, (sx, sy) = device_shell(kind, content.size)
    shadow = device_shadow(kind, content.size)
    x = cx - shell.width // 2
    canvas.paste(shadow, (x - 60, top - 60 + 22), shadow)
    canvas.paste(shell, (x, top), shell)
    canvas.paste(content, (x + sx, top + sy), rounded_mask(content.size, max(6, content.size[0] // 160)))
    return top + shell.height, shell.width


@lru_cache(maxsize=32)
def headline_layer(chapter: str, text: str) -> Image.Image:
    layer = Image.new("RGBA", (W, 190), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    small = font(SANS, 22, 650)
    pw = small.getlength(chapter) + 36
    d.rounded_rectangle(((W - pw) / 2, 30, (W + pw) / 2, 70), 20, fill=PILL_BG)
    d.text((W // 2, 50), chapter, font=small, fill=PILL_TEXT, anchor="mm")
    if text:
        big = font(SANS, 50, 700)
        lines = wrap(text, big, 1560)
        if len(lines) > 1:
            big = font(SANS, 42, 700)
            lines = wrap(text, big, 1660)
        y = 92
        for line in lines:
            d.text((W // 2, y), line, font=big, fill=INK, anchor="mt")
            y += big.size + 8
    return layer


@lru_cache(maxsize=4)
def card_layer(head: str, line: str, pill: str) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((W // 2, H // 2 - 30), head, font=font(SERIF, 150, 600), fill=INK, anchor="ms")
    small = font(SANS, 40, 500)
    for i, part in enumerate(wrap(line, small, 1400)):
        d.text((W // 2, H // 2 + 40 + i * 54), part, font=small, fill=PENCIL, anchor="mt")
    if pill:
        f = font(SANS, 24, 650)
        pw = f.getlength(pill) + 40
        y = H // 2 + 150
        d.rounded_rectangle(((W - pw) / 2, y, (W + pw) / 2, y + 46), 23, fill=PILL_BG)
        d.text((W // 2, y + 23), pill, font=f, fill=PILL_TEXT, anchor="mm")
    return layer


@lru_cache(maxsize=4)
def chapter_layer(n: int, title: str) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(SANS, 26, 650)
    label = f"Part {n} of 3"
    pw = f.getlength(label) + 40
    d.rounded_rectangle(((W - pw) / 2, H // 2 - 110, (W + pw) / 2, H // 2 - 62), 24, fill=PILL_BG)
    d.text((W // 2, H // 2 - 86), label, font=f, fill=PILL_TEXT, anchor="mm")
    d.text((W // 2, H // 2 - 20), title, font=font(SERIF, 84, 600), fill=INK, anchor="mt")
    return layer


def on_stage(layer: Image.Image) -> Image.Image:
    canvas = stage()
    canvas.paste(layer, (0, 0), layer)
    return canvas


CHAPTERS = {0: "The lesson starts", 1: "1  The teacher writes the lesson", 2: "2  A student works with the tutor", 3: "3  What the teacher sees"}

# ---------- scenes ----------


def source_times(start: float, end: float, tempo: float) -> list[float]:
    times, t = [], start
    while t < end:
        times.append(t)
        t += speed_at(t) * tempo / FPS
    return times


def ease(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def lerp(a, b, u):
    return tuple(x + (y - x) * u for x, y in zip(a, b, strict=True))


def scene_length(scene: dict, tempo: float) -> int:
    if "seconds" in scene:
        return round(scene["seconds"] * FPS)
    if "glide" in scene:
        return round(scene["keys"][-1][0] * FPS)
    return len(source_times(when(scene["from"]), when(scene["to"]), scene.get("tempo", tempo)))


def headlined(canvas: Image.Image, chapter: str, heads: list, i: int, captions: bool) -> Image.Image:
    """The chapter pill and the headline in force at frame i, fading in from the one before."""
    shown = [(f0, text) for f0, text in heads if i >= f0]
    layer = headline_layer(chapter, shown[-1][1] if captions and shown else "")
    if captions and len(shown) >= 2 and i - shown[-1][0] < TEXT_FADE:
        before = headline_layer(chapter, shown[-2][1])
        layer = Image.blend(before, layer, (i - shown[-1][0] + 1) / TEXT_FADE)
    canvas.paste(layer, (0, 0), layer)
    return canvas


def scene_frames(scene: dict, tempo: float, captions: bool):
    """Every frame of one scene, in order."""
    if "card" in scene:
        layer = card_layer(*scene["card"])
        for _ in range(scene_length(scene, tempo)):
            yield on_stage(layer)
        return
    if "seconds" in scene:
        layer = chapter_layer(*scene["chapter"])
        for _ in range(scene_length(scene, tempo)):
            yield on_stage(layer)
        return

    chapter = CHAPTERS[scene["chapter"]]
    if "glide" in scene:
        name = scene["glide"]
        _, _, t = tall_capture(name)
        bx, by, _, bh = t["box"]
        rect = clamp(CAMERAS[scene["camera"]])
        cam_h = rect[2] * CONTENT[1] / CONTENT[0]  # the camera's height on the screen, in CSS px
        # Stop the scroll when the last line of content reaches the bottom of the camera frame,
        # not the bottom of the scroll area (which can run on into empty space).
        reach = content_bottom(name) - (rect[1] + cam_h - by)
        most = min(max(reach, 0.0), t["total"] - bh)
        kind = "laptop" if scene["screen"] == "teacher" else "tablet"
        heads = sorted((round(sec * FPS), text) for sec, text in scene.get("headlines", []))
        for i in range(scene_length(scene, tempo)):
            canvas = stage()
            screen = glided(name, scrolled_to(scene["keys"], i / FPS, most))
            place(canvas, crop_view(screen, rect, CONTENT), kind, W // 2, DEVICE_TOP)
            yield headlined(canvas, chapter, heads, i, captions)
        return

    tempo = scene.get("tempo", tempo)
    times = source_times(when(scene["from"]), when(scene["to"]), tempo)

    def starts(pairs):
        """Each headline or camera from the first frame at or after its moment."""
        out = []
        for moment, value in pairs:
            if moment.split("+")[0].split("-")[0] in MARKS:
                out.append((bisect.bisect_left(times, when(moment)), value))
        return sorted(out, key=lambda p: p[0])

    heads = starts(scene.get("headlines", []))
    cams = starts([(m, CAMERAS[c]) for m, c in scene.get("cameras", [])])
    for i, t in enumerate(times):
        canvas = stage()
        if scene.get("split"):
            top, label = 262, font(SANS, 26, 650)
            for screen, kind, cx, words in (("teacher", "laptop", W // 2 - 445, "The teacher's laptop"),
                                            ("student", "tablet", W // 2 + 470, "A student's tablet")):
                bottom, _ = place(canvas, smooth(screen, t, FULL, SPLIT), kind, cx, top)
                ImageDraw.Draw(canvas).text((cx, bottom + 34), words, font=label, fill=PENCIL, anchor="mt")
        else:
            # Each camera move starts from wherever the last one had got to.
            rect = cams[0][1] if cams else FULL
            for f0, target in cams[1:]:
                if i < f0:
                    break
                rect = lerp(rect, target, ease((i - f0) / MOVE))
            kind = "laptop" if scene["screen"] == "teacher" else "tablet"
            place(canvas, smooth(scene["screen"], t, clamp(rect), CONTENT), kind, W // 2, DEVICE_TOP)
        yield headlined(canvas, chapter, heads, i, captions)


def render(name: str, tempo: float, captions: bool) -> Path:
    target = OUT_DIR / f"{name}.mp4"
    ff = subprocess.Popen(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(target)],
        stdin=subprocess.PIPE,
    )
    previous, count = None, 0
    for scene in SCENES:
        last = None
        for n, img in enumerate(scene_frames(scene, tempo, captions)):
            # The first frames of a scene dissolve from the last frame of the one before.
            if previous is not None and n < FADE:
                img = Image.blend(previous, img, (n + 1) / (FADE + 1))
            ff.stdin.write(img.tobytes())
            last = img
            count += 1
        previous = last
    ff.stdin.close()
    ff.wait()
    print(f"{target}  {target.stat().st_size / 1e6:.1f} MB, {count / FPS:.1f} s")
    return target


def stills(tempo: float) -> None:
    """A few frames from every scene, for checking the cameras and headlines before a render."""
    out = HERE / "stills"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()
    total = 0
    for k, scene in enumerate(SCENES):
        n = scene_length(scene, tempo)
        total += n
        picks = {n // 2} if "seconds" in scene else {n // 6, n // 2, 5 * n // 6, n - 1}
        for j, img in enumerate(scene_frames(scene, tempo, True)):
            if j in picks:
                img.save(out / f"{k:02d}-{j:04d}.jpg", quality=88)
        print(f"scene {k:2d}: {n / FPS:5.1f} s")
    print(f"total {total / FPS:.1f} s; stills in {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tempo", type=float, default=1.5)
    parser.add_argument("--name", default="genai4ed-research-meeting")
    parser.add_argument("--stills", action="store_true", help="only save frames to check the cameras")
    a = parser.parse_args()
    missing = [m for m in ("begin", "card_scroll", "approve", "start", "opening", "near_reply", "note_arrived",
                           "got_reply", "board_struggling", "note_reply", "summary", "summary_scroll", "end")
               if m not in MARKS]
    missing += [f"tall capture {g}" for g in ("card_scroll", "summary_scroll") if g not in TALL]
    if missing:
        raise SystemExit(f"the recording has no mark for: {', '.join(missing)}")
    # A tall capture whose pane sits off the screen, or does not scroll, would render as a
    # silent blank glide; refuse it with a clear message instead (an old take once did this).
    for g in ("card_scroll", "summary_scroll"):
        x, y, w, h = TALL[g]["box"]
        total = TALL[g]["total"]
        if x < 0 or y < 0 or x + w > SRC_W + 1 or y + h > SRC_H + 1:
            raise SystemExit(f"tall capture {g}: pane box {TALL[g]['box']} is off the {SRC_W} by {SRC_H} screen")
        if total <= h + 1:
            raise SystemExit(f"tall capture {g}: the pane does not scroll (total {total} <= height {round(h)})")
        shot = Image.open(HERE / "tall" / TALL[g]["image"])
        if abs(shot.height - round(total * SCALE)) > 2 * SCALE:
            raise SystemExit(f"tall capture {g}: image {shot.size} does not match total {total}")
    if a.stills:
        stills(a.tempo)
    else:
        render(a.name, a.tempo, captions=True)
        render(f"{a.name}-no-captions", a.tempo, captions=False)
