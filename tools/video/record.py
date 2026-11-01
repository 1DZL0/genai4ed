"""Record one live lesson on two screens for the demo video: the teacher writing the lesson,
starting it, one student working with the tutor and getting stuck, the teacher stepping in, the
lesson ending with its summary. Both screens are recorded the whole time; every moment worth
cutting to gets a named mark, so tools/video/build.py can show the student's conversation
first and then the teacher's view of the same minutes.

The student on camera is not scripted line by line: a model writes each message from a
persona, a beat (a right start, a real slip, a near miss, getting it) and what the tutor
actually said, through backend/bench/pupil_line.py, so the two sides talk about the same thing.
Scrolls are not filmed either: at each scroll mark the teacher's card pane is captured whole,
as one tall image, and the editor glides over it at full frame rate.

From the repo root, with the containers up:

    python tools/video/record.py

Writes frames/teacher/*.jpg, frames/student/*.jpg, tall/*.png and timeline.json into
.superdesign/tmp/video-2026-10-26/ (ignored by git). Pseudonyms only; nothing from .env is
ever on screen. The three students off camera are driven by backend/bench/live_pupils.py.
Never touch the demo teacher's thread while this runs: the card on screen follows the server.
"""

import asyncio
import base64
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

WEB = "http://127.0.0.1:3000"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".superdesign" / "tmp" / "video-2026-10-26"
TEACHER = "teacher-demo"
CLASS = "9W Maths"
PERSONAS = ("steady", "quiet", "steady")  # the three students off camera
VIEW = {"width": 1440, "height": 900}  # a laptop screen, recorded at twice the pixels
SCALE = 2
FAST = 8  # while the agent drafts for the teacher
THINK = 5  # while the tutor reads what the student wrote: the dots stay visible
TYPE_T = 6  # ms per character for the teacher, who types like a fast-forward
KEYS = (45, 110)  # ms per character for the student, varied word by word

T1 = (
    "Year 9, percentages of amounts, 20 minutes, no calculators. Open with one quick question "
    "to everyone: what is 10% of 60, and how did you get it? That tells us who remembers that "
    "per cent means out of 100 and that 10% is a tenth. Then the main one, 30% of 60, by "
    "finding 10% and multiplying up; let them try it before any working is shown. Then four of "
    "their own, building up to a sale price: a £45 jacket with 20% off. Finish with a "
    "challenge: is 30% of 50 the same as 50% of 30, and why?"
)
T2 = (
    "Hints any time, but a worked step only after one wrong try, and never give the final "
    "answer. Tell me straight away if anyone is struggling or upset. Everything else can go in "
    "the record."
)
NOTE = "Tell {name} to find 10% of 60 first and write it down, then we only need three of those."

# The student on camera: who they are, and what each of their turns must do. The words are the
# model's, written against the tutor's actual message, so they answer it.
VOICE = "a Year 9 pupil, 13 years old"
ON_CAMERA = {
    "who": (
        "A Year 9 pupil, 13, who types like they text a friend: one short line, 4 to 14 words, "
        "all lowercase, plain kid words, cos instead of because, numbers as digits; when not "
        "sure they end with a question mark, like 'is it 7? i just halved it'. No grown-up "
        "words (no 'I believe', 'therefore', 'certainly', 'so basically'), no exclamation "
        "marks, no emojis, no dashes, no greetings. Never repeats the tutor's question back, "
        "never says they are an AI, never apologises, never gives up, never rude. Always "
        "answers the exact thing the tutor asked in its latest message."
    ),
    "beats": {
        "warm": (
            "Answer the tutor's latest question correctly, like a kid. If it asked for 10% of "
            "60, say 6 and a few words on how you got it (knock the 0 off, or 60 divided by 10). "
            "If it asked what per cent means, say it in your own kid words (something like out "
            "of 100). One short line, 4 to 12 words, lowercase, no exclamation marks."
        ),
        "slip": (
            "The tutor asked for 30% of 60. You make a real mistake: you think the answer is "
            "just 30, because the question says 30 percent (or you 'take the 30 off'). Say 30 "
            "as your answer and show that wrong thinking in a few words, fairly sure of "
            "yourself, maybe a question mark at the end. Start with its or with 30, never with "
            "the words 30% of 60. Do not use 10% or 6, do not get 18, and do not say it is "
            "wrong. One short line, 4 to 12 words."
        ),
        "near": (
            "Use the tutor's idea on the real question, 30% of 60, but only part way: write "
            "10% of 60 = 6, then add just two of them, 6 + 6 = 12, and end on 12 with a question "
            "mark, as if you think it might be right. If the tutor asked how many lots, say 2 "
            "lots. One line of working like a kid, 5 to 14 words. Do not count three, do not "
            "say 18, do not use the word hopefully."
        ),
        "got": (
            "Start with ohh or wait so, then do exactly what the tutor just said, in one line: "
            "10% of 60 = 6, then three of those as 6 + 6 + 6 = 18, and finish with so 30% of 60 "
            "is 18. Do not write the words three lots, the sum shows it. You are sure now: no "
            "question mark. Under 18 words counting the + and = signs, lowercase, no "
            "exclamation marks."
        ),
        "spare": (
            "Answer the tutor's latest question correctly with one short line of working, like "
            "a kid: 4 to 14 words, lowercase, numbers not words. If it asks why, say the reason "
            "in a few kid words. You are fairly sure of this one, so no question mark unless "
            "you really need it."
        ),
    },
}
# What each beat's line has to contain (any one of), checked before it is typed. Warm allows
# the meaning answer too, in case the tutor opens by asking what per cent means.
MUST = {"warm": ["6", "100"], "slip": ["30"], "near": ["12"], "got": ["18"], "spare": []}
# What the student types if the writer gives nothing usable three times: on the arc, in the
# same voice, so a flat model reply cannot spoil the take.
FALLBACK_LINES = {
    "warm": "6, i just did 60 divided by 10",
    "slip": "its 30 cos it says 30 percent right?",
    "near": "so 10% is 6, then 6 + 6 = 12?",
    "got": "ohh wait so 10% of 60 = 6, 6 + 6 + 6 = 18, so 30% of 60 is 18",
    "spare": "3 lots so 6 + 6 + 6 = 18",
}

PANE = "#panel-card"  # the teacher's card pane, the one that scrolls
# On camera only: no scrollbars, and the pages' own smooth scrolls become instant. A smooth
# scroll filmed at twelve frames a second is a staircase; a cut is clean.
ON_CAMERA_JS = """
(() => {
  const into = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (o) {
    into.call(this, o && typeof o === 'object' ? {...o, behavior: 'instant'} : o);
  };
  const to = Element.prototype.scrollTo;
  Element.prototype.scrollTo = function (...a) {
    if (a.length === 1 && a[0] && typeof a[0] === 'object') a[0] = {...a[0], behavior: 'instant'};
    return to.apply(this, a);
  };
  document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = '#panel-card, [role=log] { scrollbar-width: none }';
    document.head.appendChild(style);
  });
})();
"""
# Let the pane grow to its whole height so one screenshot holds all of it: no height cap, no
# inner scroll, and the heading laid in place instead of stuck to the top. The old style is
# handed back so it can be put on again the moment the shot is taken.
EXPAND_JS = """(sel) => {
  const el = document.querySelector(sel);
  const head = el.querySelector('.sticky');
  const header = head ? head.getBoundingClientRect().height : 0;
  const saved = {el: el.getAttribute('style') || '', head: head ? (head.getAttribute('style') || '') : ''};
  // flex-none and align-start stop the row from stretching the pane back to the window height;
  // height auto then makes it exactly as tall as its content (no trailing empty scroll space).
  el.style.flex = 'none';
  el.style.alignSelf = 'flex-start';
  el.style.height = 'auto';
  el.style.maxHeight = 'none';
  el.style.overflow = 'visible';
  if (head) head.style.position = 'static';
  return {width: el.clientWidth, header, total: el.scrollHeight, saved};
}"""
RESTORE_JS = """([sel, saved]) => {
  const el = document.querySelector(sel);
  const head = el.querySelector('.sticky');
  el.setAttribute('style', saved.el);
  if (head) head.setAttribute('style', saved.head);
  el.scrollTop = 0;
}"""

marks: list[dict] = []
tall_captures: dict[str, dict] = {}
paused: set[str] = set()  # screens whose camera waits while a tall capture moves the pane


def speed(n: float) -> None:
    marks.append({"t": time.time(), "speed": n})


def mark(name: str) -> None:
    marks.append({"t": time.time(), "mark": name})


def site_password() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("SITE_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no SITE_PASSWORD in .env")


async def film(page, name: str, frames: list, stop: asyncio.Event) -> None:
    """Film one screen at twice its pixels, as fast as the browser will draw it (about 12
    frames a second), keeping only frames that changed. The browser's own screencast cannot do
    this: it always delivers frames at screen size, which zooms then blur."""
    folder = OUT / "frames" / name
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.jpg"):
        old.unlink()
    cdp = await page.context.new_cdp_session(page)
    last = None
    while not stop.is_set():
        if name in paused:
            await asyncio.sleep(0.05)
            continue
        t = time.time()
        try:
            # The clip is in page coordinates: follow the page's own scroll, or a scroll that runs
            # on past a pane into the whole page leaves a blank band at the top of the frame.
            view = (await asyncio.wait_for(cdp.send("Page.getLayoutMetrics"), timeout=2.0))["cssVisualViewport"]
            clip = {"x": view["pageX"], "y": view["pageY"], "width": VIEW["width"],
                    "height": VIEW["height"], "scale": SCALE}
            # A grab can hang for ever when the page navigates under it: never wait long, and
            # start a fresh session if it does, or the whole take freezes at the end.
            shot = await asyncio.wait_for(
                cdp.send(
                    "Page.captureScreenshot",
                    {"format": "jpeg", "quality": 88, "optimizeForSpeed": True, "clip": clip},
                ),
                timeout=2.0,
            )
        except Exception:  # noqa: BLE001 - mid-navigation, or a stuck grab
            await asyncio.sleep(0.1)
            try:
                cdp = await page.context.new_cdp_session(page)
            except Exception:  # noqa: BLE001 - the page is going away; the loop ends with stop
                pass
            continue
        if shot["data"] != last:
            last = shot["data"]
            path = folder / f"{len(frames):05d}.jpg"
            path.write_bytes(base64.b64decode(shot["data"]))
            frames.append({"t": t, "file": path.name})


async def tall(page, name: str, screen: str = "teacher") -> None:
    """The card pane's whole content as one tall image, with the screen as it stood, so the
    editor can glide over it at full frame rate: a scroll filmed live at twelve frames a second
    is a staircase. Taken in one shot by letting the pane grow to its full height (a raw
    clipped capture of a sub-pane came back blank while the film loop held a session on the
    page). The camera waits while the pane grows, and the pane is put back before it resumes."""
    paused.add(screen)
    await asyncio.sleep(0.4)  # let the film loop's last grab finish before the pane is touched
    folder = OUT / "tall"
    folder.mkdir(parents=True, exist_ok=True)
    pane = page.locator(PANE)
    try:
        box = await pane.bounding_box()  # where the pane sits at its normal size, for placement
        meta = await page.evaluate(EXPAND_JS, PANE)
        # The window is grown as tall as the content (plus where the pane starts down the page):
        # an element screenshot otherwise stops at the window height, so a card longer than the
        # screen came back cut off at one screenful.
        tall_h = min(int(meta["total"] + box["y"]) + 80, 8000)
        await page.set_viewport_size({"width": VIEW["width"], "height": tall_h})
        await asyncio.sleep(0.4)  # reflow and paint the content that was below the fold
        try:
            png = await pane.screenshot(type="png", timeout=20000)  # the whole pane, now tall
        finally:
            await page.evaluate(RESTORE_JS, [PANE, meta["saved"]])
            await page.set_viewport_size(VIEW)
        (folder / f"{name}.png").write_bytes(png)
        await asyncio.sleep(0.3)  # the pane and window are back to normal: now the screen as it stood
        base = await page.screenshot(
            type="jpeg", quality=92, clip={"x": 0, "y": 0, "width": VIEW["width"], "height": VIEW["height"]}
        )
        (folder / f"{name}-base.jpg").write_bytes(base)
        tall_captures[name] = {
            "t": time.time(), "base": f"{name}-base.jpg", "image": f"{name}.png",
            "box": [box["x"], box["y"], box["width"], box["height"]],
            "header": meta["header"], "total": meta["total"],
        }
    finally:
        await asyncio.sleep(0.2)
        paused.discard(screen)


async def wait_for(check, timeout=150, every=0.5):
    end = time.time() + timeout
    while time.time() < end:
        if await check():
            return
        await asyncio.sleep(every)
    raise TimeoutError("the page never showed what we waited for")


async def agent_lines(ctx, sid) -> int:
    view = await (await ctx.request.get(f"{WEB}/api/learn/{sid}")).json()
    return sum(1 for line in view["lines"] if line["who"] == "agent")


async def thread_agent_count(tctx) -> int:
    thread = await (await tctx.request.get(f"{WEB}/api/teacher/thread")).json()
    return sum(1 for m in thread["messages"] if m["role"] == "agent" and m["text"])


async def clean(tctx) -> None:
    """Off camera: every alert dealt with, every run ended, every lesson removed, the thread
    cleared. Remove refuses a lesson while its alerts are open, so the order matters."""
    act = f"{WEB}/api/teacher/thread/actions"
    lessons = (await (await tctx.request.get(f"{WEB}/api/teacher/thread/lessons")).json())["lessons"]
    for lesson in lessons:
        runs = [r["session_id"] for r in (lesson.get("live"), lesson.get("last_run")) if r]
        for sid in runs:
            card = (await (await tctx.request.post(act, data={"action": "show_class", "session_id": sid})).json())["showing"]
            for alert in card.get("alerts", []):
                if alert.get("status", "open") == "open":
                    key = alert.get("exception_id") or alert.get("id")
                    await tctx.request.post(f"{WEB}/api/teacher/exceptions/{key}/acknowledge")
            if card.get("status") in ("open", "paused"):
                await tctx.request.post(act, data={"action": "end", "session_id": sid})
        r = await tctx.request.post(act, data={"action": "delete_lesson", "lesson_id": lesson["lesson_id"]})
        assert r.ok, await r.text()
    await tctx.request.post(act, data={"action": "clear"})


async def pupil_line(sid: str, beat: str, lines: list[dict]) -> str:
    """The student's next message, written by the model from the beat and the conversation."""
    proc = await asyncio.create_subprocess_exec(
        "uv", "run", "python", "-m", "bench.pupil_line",
        cwd=ROOT / "backend",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    ask = {"session": sid, "voice": VOICE, "who": ON_CAMERA["who"], "beat": ON_CAMERA["beats"][beat],
           "must": MUST[beat], "lines": lines}
    out, err = await proc.communicate(json.dumps(ask).encode("utf-8"))
    text = out.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not text:
        # The helper tried three times and nothing would do: the take goes on with our line.
        print(f"{beat}: writer fell back ({err.decode('utf-8', 'replace').strip()[-400:]})")
        return FALLBACK_LINES[beat]
    return text


async def type_like_a_pupil(box, text: str) -> None:
    """Word by word at an uneven speed, with a pause now and then: a hand, not a script."""
    words = text.split(" ")
    for i, word in enumerate(words):
        tail = " " if i < len(words) - 1 else ""
        await box.press_sequentially(word + tail, delay=random.randint(*KEYS))
        if word.endswith(("?", ".", ",")):
            await asyncio.sleep(random.uniform(0.25, 0.6))
        elif random.random() < 0.15:
            await asyncio.sleep(random.uniform(0.2, 0.5))


async def main() -> None:
    # The take log is redirected to a file: on Windows a print of a pupil's £ or ÷ would raise
    # UnicodeEncodeError and end the recording, so never let a print do that.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    password = site_password()
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        # A browser each, so the two screens are filmed in parallel at full speed.
        tbrowser = await p.chromium.launch(channel="msedge", headless=True)
        sbrowser = await p.chromium.launch(channel="msedge", headless=True)
        tctx = await tbrowser.new_context(viewport=VIEW, device_scale_factor=SCALE)
        sctx = await sbrowser.new_context(viewport=VIEW, device_scale_factor=SCALE)
        for ctx in (tctx, sctx):
            await ctx.add_init_script(ON_CAMERA_JS)
            await ctx.request.post(f"{WEB}/gate/unlock", form={"password": password}, max_redirects=0)

        # Off camera: the teacher, a fresh class of four, a clean slate.
        r = await tctx.request.post(f"{WEB}/api/auth/demo", data={"role": "teacher", "username": TEACHER, "password": "demo"})
        assert r.ok, await r.text()
        classes = await (await tctx.request.get(f"{WEB}/api/teacher/classes")).json()
        klass = next((k for k in classes if k["label"] == CLASS), None)
        if klass is None:
            made = await tctx.request.post(f"{WEB}/api/teacher/classes", data={"label": CLASS, "students": 4})
            assert made.ok, await made.text()
            klass = await made.json()
        roster = await (await tctx.request.get(f"{WEB}/api/teacher/classes/{klass['id']}/students")).json()
        names = [s["pseudonym"] for s in roster]
        assert len(names) >= 4, names
        on_camera, off_camera = names[1], [names[0], *names[2:4]]
        await clean(tctx)
        r = await sctx.request.post(f"{WEB}/api/auth/demo", data={"role": "student", "username": on_camera, "password": "demo"})
        assert r.ok, await r.text()
        print("on camera:", on_camera, "off camera:", off_camera)

        teacher = await tctx.new_page()
        student = await sctx.new_page()
        await student.goto(f"{WEB}/student")
        tframes, sframes = [], []
        stop = asyncio.Event()
        cameras = [
            asyncio.ensure_future(film(teacher, "teacher", tframes, stop)),
            asyncio.ensure_future(film(student, "student", sframes, stop)),
        ]

        async def teacher_says(text: str, name: str, read: float) -> None:
            chat = teacher.get_by_placeholder("Tell the agent what to teach, or ask about a class")
            await chat.click()
            mark(f"{name}_typing")
            await chat.press_sequentially(text, delay=TYPE_T)
            await asyncio.sleep(0.5)
            before = await thread_agent_count(tctx)
            await chat.press("Enter")
            mark(f"{name}_sent")
            await asyncio.sleep(1.0)
            speed(FAST)
            await wait_for(lambda: _thread_more(tctx, before), timeout=180)
            speed(1)
            mark(f"{name}_reply")
            await asyncio.sleep(read)

        # 1. The teacher writes the lesson.
        speed(1)
        await teacher.goto(f"{WEB}/teacher")
        await teacher.get_by_placeholder("Tell the agent what to teach, or ask about a class").wait_for(timeout=30000)
        await asyncio.sleep(1.5)
        mark("begin")
        await teacher_says(T1, "lesson", read=2.5)
        await teacher_says(T2, "rules", read=1.5)
        mark("card_scroll")
        await tall(teacher, "card_scroll")
        await asyncio.sleep(1.0)
        mark("approve")
        await teacher.get_by_role("button", name="Approve", exact=True).first.click()
        await asyncio.sleep(2.5)
        select = teacher.get_by_label("Class to teach").first
        if await select.count():
            await select.select_option(label=f"{CLASS} ({len(names)})")
            await asyncio.sleep(0.8)
        mark("start")
        await teacher.get_by_role("button", name=f"Start with {CLASS}").first.click()
        await asyncio.sleep(1.0)
        speed(3)
        await wait_for(lambda: _live(tctx), timeout=60)
        speed(1)
        mark("live")
        lessons = (await (await tctx.request.get(f"{WEB}/api/teacher/thread/lessons")).json())["lessons"]
        sid = next(x["live"]["session_id"] for x in lessons if x["live"])
        await asyncio.sleep(1.5)

        # 2. The student opens it, with the other three starting off camera.
        others = subprocess.Popen(
            ["uv", "run", "python", "-m", "bench.live_pupils", "--session", sid, "--teacher", TEACHER,
             "--pupils", ",".join(f"{n}:{p}" for n, p in zip(off_camera, PERSONAS, strict=True)),
             "--turns", "6", "--pace", "9"],
            cwd=ROOT / "backend",
            stdout=open(OUT / "off-camera.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        mark("student_open")
        await student.goto(f"{WEB}/student/{sid}")
        await student.locator("h1").first.wait_for(timeout=30000)
        speed(FAST)
        await wait_for(lambda: _more(sctx, sid, 0))
        await wait_for(lambda: _tutor_lines(student, 1), timeout=30)
        speed(1)
        mark("opening")

        async def conversation() -> list[dict]:
            view = await (await sctx.request.get(f"{WEB}/api/learn/{sid}")).json()
            # Only the two voices the writer knows: a 'note' line would be read as the pupil's own.
            return [{"who": x["who"], "text": x["text"]} for x in view["lines"] if x["who"] in ("agent", "student")]

        async def settled(line: asyncio.Future) -> str:
            """The writer's line, speeding past any wait for it so it is never filmed as dead air."""
            if line.done():
                return await line
            speed(FAST)
            try:
                return await line
            finally:
                speed(1)

        async def next_line(beat: str) -> asyncio.Future:
            """Starts writing the student's next message now, while they 'read' the reply."""
            return asyncio.ensure_future(pupil_line(sid, beat, await conversation()))

        async def student_says(text: str, name: str) -> None:
            shown = await student.get_by_text("Tutor", exact=True).count()
            box = student.get_by_placeholder("Write your answer or ask a question")
            await box.click()
            await asyncio.sleep(0.4)
            mark(f"{name}_typing")
            await type_like_a_pupil(box, text)
            await asyncio.sleep(random.uniform(0.4, 0.8))
            await box.press("Enter")
            mark(f"{name}_sent")
            await asyncio.sleep(1.0)
            speed(THINK)
            await wait_for(lambda: _tutor_lines(student, shown + 1))
            speed(1)
            mark(f"{name}_reply")
            print(f"{name}: {text}")

        async def student_presses(labels: list[str], name: str) -> None:
            """The first of these help buttons the page offers, so there is always a fallback."""
            shown = await student.get_by_text("Tutor", exact=True).count()
            button = None
            for label in labels:
                candidate = student.get_by_role("button", name=label).first
                if await candidate.count() and await candidate.is_enabled():
                    button = candidate
                    break
            assert button is not None, f"none of {labels} on the page"
            mark(f"{name}_press")
            await button.click()
            await asyncio.sleep(1.0)
            speed(THINK)
            await wait_for(lambda: _tutor_lines(student, shown + 1))
            speed(1)
            mark(f"{name}_reply")

        async def tutor_asks_30() -> bool:
            """The tutor's last message ends on a question about 30% of 60: time for the slip.
            A loose match on "30%" would fire on "before we do 30% of 60, how did you get 6?"."""
            said = [x["text"] for x in await conversation() if x["who"] == "agent"]
            return bool(said) and re.search(r"30\s?(%|per\s?cent).{0,40}\?\s*$", said[-1], re.S) is not None

        # A right start, then the slip, once the tutor has asked the main question.
        line = await next_line("warm")
        await asyncio.sleep(4.0)
        await student_says(await settled(line), "warm")
        for n in range(2):
            if await tutor_asks_30():
                break
            line = await next_line("spare")
            await asyncio.sleep(3.5)
            await student_says(await settled(line), f"warm{n + 2}")
        line = await next_line("slip")
        await asyncio.sleep(4.5)
        await student_says(await settled(line), "slip")
        await asyncio.sleep(4.5)
        await student_presses(["Give me an example", "Explain it another way", "I don't understand"], "example")
        line = await next_line("near")
        await asyncio.sleep(5.0)
        await student_says(await settled(line), "near")
        await asyncio.sleep(3.5)

        # 3. The teacher sees it and steps in through the agent.
        speed(FAST)
        await wait_for(lambda: _board_shows(teacher, on_camera), timeout=90)
        speed(1)
        mark("board_struggling")
        await asyncio.sleep(3.5)
        shown = await student.get_by_text("Tutor", exact=True).count()
        await teacher_says(NOTE.format(name=on_camera), "note", read=2.5)
        speed(FAST)
        await wait_for(lambda: _tutor_lines(student, shown + 1), timeout=120)
        speed(1)
        mark("note_arrived")
        line = await next_line("got")
        await asyncio.sleep(5.0)
        await student_says(await settled(line), "got")
        await asyncio.sleep(5.0)

        # 4. The lesson ends; the agent writes the summary for the teacher to check.
        whole = teacher.get_by_role("button", name="The whole class")
        if await whole.count():
            await whole.first.click()
        speed(FAST)
        await asyncio.sleep(9)
        speed(1)
        mark("board_later")
        await asyncio.sleep(3)
        # End and Write the summary live on the class card: if the agent's answer to the note
        # left a different card up, put the class card back (off camera, as clean() does).
        if not await teacher.get_by_role("button", name="End the lesson").count():
            await tctx.request.post(
                f"{WEB}/api/teacher/thread/actions", data={"action": "show_class", "session_id": sid}
            )
            await asyncio.sleep(2.0)
        end = teacher.get_by_role("button", name="End the lesson").first
        if await end.count():
            mark("end_press")
            await end.click()
            await asyncio.sleep(1.2)
            confirm = teacher.get_by_role("button", name="End it").first
            if await confirm.count():
                await confirm.click()
            speed(FAST)
            await wait_for(lambda: _ended(tctx, sid), timeout=240)
            speed(1)
            mark("ended")
            await asyncio.sleep(2)
            summary = teacher.get_by_role("button", name="Write the summary").first
            if await summary.count():
                mark("summary_press")
                await summary.click()
                await asyncio.sleep(1)
                speed(FAST)
                await wait_for(lambda: _summarised(tctx), timeout=300)
                speed(1)
                await asyncio.sleep(1)
                mark("summary")
                await asyncio.sleep(4)
                mark("summary_scroll")
                await tall(teacher, "summary_scroll")
                await asyncio.sleep(1.5)
        mark("end")
        await asyncio.sleep(1)
        stop.set()
        # Save the timeline the moment the cameras stop, before anything that can fail: a late
        # error in the browser close or the off-camera wait must not throw the whole take away.
        try:
            await asyncio.wait_for(asyncio.gather(*cameras), timeout=15)
        finally:
            write_timeline(sid, on_camera, tframes, sframes)
        await tbrowser.close()
        await sbrowser.close()
        if others.poll() is None:
            others.wait(timeout=120)
    print(f"session {sid}: {len(tframes)} teacher frames, {len(sframes)} student frames")


def write_timeline(sid: str, pupil: str, tframes: list, sframes: list) -> None:
    (OUT / "timeline.json").write_text(
        json.dumps(
            {"session_id": sid, "pupil": pupil, "view": VIEW, "scale": SCALE,
             "marks": marks, "tall": tall_captures, "teacher": tframes, "student": sframes},
            indent=1,
        ),
        encoding="utf-8",
    )


async def _more(ctx, sid, before: int) -> bool:
    return await agent_lines(ctx, sid) > before


async def _tutor_lines(page, n: int) -> bool:
    """The student's page shows at least n tutor turns: what the camera sees, not the server."""
    return await page.get_by_text("Tutor", exact=True).count() >= n


async def _thread_more(tctx, before: int) -> bool:
    return await thread_agent_count(tctx) > before


async def _live(tctx) -> bool:
    lessons = (await (await tctx.request.get(f"{WEB}/api/teacher/thread/lessons")).json())["lessons"]
    return any(x["live"] for x in lessons)


async def _ended(tctx, sid) -> bool:
    lessons = (await (await tctx.request.get(f"{WEB}/api/teacher/thread/lessons")).json())["lessons"]
    return not any(x["live"] and x["live"]["session_id"] == sid for x in lessons)


async def _summarised(tctx) -> bool:
    thread = await (await tctx.request.get(f"{WEB}/api/teacher/thread")).json()
    card = thread.get("showing") or {}
    return card.get("type") == "outcomes" and len(card.get("outcomes") or []) > 0


async def _board_shows(page, pseudonym: str) -> bool:
    return await page.get_by_text(pseudonym).first.count() > 0 and await page.get_by_text("Struggling").first.count() > 0


if __name__ == "__main__":
    asyncio.run(main())
