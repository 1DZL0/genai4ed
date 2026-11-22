"""A look at the teacher's screens in a browser, reading only, for the school day (S5).

Run it as
    uv run -q --no-project --with "playwright==1.64.1" python -I look.py
followed by the website, the test API, the teacher's name and the folder for what it writes.

Both addresses must be test ones on this machine (127.0.0.1, the port named, never the live site's
3000 or 8000), and two different ones. The teacher signs in on the test API itself (demo sign-in),
and that sign-in is handed to the browser for the website, which must then show the teacher's
screen with it. A website whose /api goes anywhere else (to the live API, when it was built without
API_INTERNAL_URL) does not, and nothing is looked at. Through the website the look only reads:
every request a page makes that is not a GET is stopped before it leaves the browser, and counts
as a problem.

At 1280 and at 400 wide it reads:
- the teacher's page, where the class view must already be on screen (the runner shows it). On a
  phone the view sits behind its own tab, and pressing the tab only switches the view;
- the research view, and the research page of the class view's lesson. These open only with the
  research key, which comes from the environment (RESEARCH_KEY) and is typed into the page's own
  key box, a password box: it is never printed, written or put on the command line. Without a key
  the research view is read as anyone sees it, with its key box, and its lesson page is not.

On each page: every pupil of the class is on the class view; nothing runs off the side; no dialog
covers the screen; no page errors; no long dashes. A teacher's page sits in a box of the screen's
height whose columns scroll by themselves, so the page as a whole never grows wider than the
screen: what runs off the side is measured in the boxes that frame and scroll the page, and as
anything reaching past the right edge of the screen, apart from the boxes made to scroll sideways
(the research tables) and text cut short on purpose. Something going wrong on one page is that
page's problem, and the look goes on. The screenshots go down each page's scrolling box a screen
at a time, so that a class of 30 is all in them.

It writes look.json and the screenshots to the folder, and exits 0 when every check passed, 1 when
one did not, and 2 when it would not start.

Only the standard library is imported at the top, so that the checks can be imported and tested
without Playwright.
"""

import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse, urlsplit

# Where the research key comes from: the runner sets it for this script alone.
KEY_ENV = "RESEARCH_KEY"
# The password the run's teachers type. Demo sign-in never checks it.
PASSWORD = "school-day"
WIDTHS = (("wide", 1280), ("phone", 400))
HEIGHT = 900
LOCAL_HOST = "127.0.0.1"
LIVE_PORTS = (3000, 8000)
# How long a page has to show what is looked for, in milliseconds. The research view reads
# every lesson on the copy, so it gets time to come up.
WAIT_MS = 30_000
# The pages, by the start of their screenshots' names: name-width-1.png, -2.png and on.
SHOT_PAGES = ("teacher", "research", "lesson")
# At most this many screenshots of a page, each overlapping the one before by this many pixels.
MOST_SHOTS = 6
OVERLAP = 40
# At most this many things that run off the side, named for each page.
MOST_WIDE = 4
# The em dash and the en dash, by number, so that this file holds neither.
LONG_DASHES = (chr(0x2014), chr(0x2013))
# How a long dash is written in a problem, which goes into a report written without them.
DASH_WRITTEN = "[long dash]"
# How many characters either side of a long dash a problem quotes.
AROUND = 30
# A dialog that keeps the teacher from the page until they answer it (the lesson clock's).
MODAL = '[role="dialog"][aria-modal="true"]'

# What runs off the side, measured in the page: ["box", name, "", pixels] for a box that is
# wider inside than the room it has, and ["edge", tag, words, pixels] for anything that reaches
# past the right edge of the screen. The boxes measured: the page, its main column and every box
# around that, the conversation and the card panel, and every box that scrolls, apart from the
# boxes made to scroll sideways and form fields. Of what reaches past the edge, only the
# outermost, and nothing inside a box made to scroll sideways or text cut short on purpose.
WIDE = """
() => {
  const root = document.documentElement;
  const screen = root.clientWidth;
  const meantToScroll = [
    "overflow-x-auto", "overflow-auto", "overflow-x-scroll", "overflow-scroll",
  ];
  const sideways = (el) => meantToScroll.some((name) => el.classList.contains(name));
  const field = (el) => ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
  const shown = (el) => {
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && getComputedStyle(el).visibility !== "hidden";
  };
  const tag = (el) =>
    el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") +
    [...el.classList].slice(0, 3).map((name) => "." + name).join("");
  const named = (el) => {
    if (el === root) return "the page";
    if (el.id === "panel-card") return "the card panel";
    if (el.id === "panel-talk") return "the conversation";
    if (el.tagName === "MAIN") return "the main column";
    return tag(el);
  };
  const all = [...document.body.querySelectorAll("*")];
  const boxes = new Set([root]);
  for (let el = document.querySelector("main"); el && el !== document.body; el = el.parentElement) {
    boxes.add(el);
  }
  for (const id of ["panel-talk", "panel-card"]) {
    const el = document.getElementById(id);
    if (el) boxes.add(el);
  }
  for (const el of all) {
    const x = getComputedStyle(el).overflowX;
    if ((x === "auto" || x === "scroll") && !sideways(el) && !field(el)) boxes.add(el);
  }
  const found = [];
  for (const el of boxes) {
    if (el !== root && !shown(el)) continue;
    const by = Math.round(el.scrollWidth - el.clientWidth);
    if (by > 1) found.push(["box", named(el), "", by]);
  }
  const past = [];
  for (const el of all) {
    if (el.getBoundingClientRect().right <= screen + 1 || !shown(el)) continue;
    if (past.some((outer) => outer.contains(el))) continue;
    let meant = false;
    for (let up = el; up && up !== document.body; up = up.parentElement) {
      if (sideways(up) || getComputedStyle(up).textOverflow === "ellipsis") {
        meant = true;
        break;
      }
    }
    if (!meant) past.push(el);
  }
  for (const el of past) {
    const by = Math.round(el.getBoundingClientRect().right - screen);
    found.push(["edge", tag(el), (el.innerText || "").slice(0, 80), by]);
  }
  return found;
}
"""

# The box a page scrolls in: the card panel on the teacher's page when it shows, else the
# nearest box around the main column that scrolls; null when the page scrolls itself.
SCROLL_BOX = """
() => {
  const shown = (el) => {
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };
  const panel = document.getElementById("panel-card");
  if (panel && shown(panel)) return panel;
  for (let el = document.querySelector("main"); el && el !== document.body; el = el.parentElement) {
    const y = getComputedStyle(el).overflowY;
    if ((y === "auto" || y === "scroll") && el.scrollHeight > el.clientHeight) return el;
  }
  return null;
}
"""


def page_problems(name: str, text: str, wide: Iterable[tuple[str, int]]) -> list[str]:
    """What is wrong with one page, from its words and what runs off the side (see
    wide_things): each of the first few things that run off the side, and the first long dash,
    quoted with the words around it."""
    problems = [f"{name}: {what} runs {by}px off the side" for what, by in list(wide)[:MOST_WIDE]]
    found = [at for at in (text.find(dash) for dash in LONG_DASHES) if at >= 0]
    if found:
        problems.append(f'{name}: a long dash in "{_around(text, min(found))}"')
    return problems


def wide_things(found: Iterable) -> list[tuple[str, int]]:
    """What runs off the side, in words, from what the page measured (WIDE): a box by what is
    in it, and anything past the right edge by its tag and its first words."""
    things = []
    for kind, label, words, by in found:
        if kind == "box":
            things.append((f"what is in {label}", int(by)))
        else:
            said = " ".join(str(words).split())[:40]
            things.append((f'{label} ("{said}")' if said else label, int(by)))
    return things


def missing_pupils(text: str, pseudonyms: Iterable[str]) -> list[str]:
    """The pseudonyms that are not in `text`, each looked for as a whole word."""
    return [p for p in pseudonyms if not re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text)]


def written_out(text: str) -> str:
    """`text` with every long dash written out."""
    for dash in LONG_DASHES:
        text = text.replace(dash, DASH_WRITTEN)
    return text


def hidden(text: str, key: str) -> str:
    """`text` with the research key taken out, wherever it is."""
    return text.replace(key, "[research key]") if key else text


def counted(n: int, thing: str) -> str:
    """How many of a thing, in words: 1 problem, 2 problems."""
    return f"{n} {thing}" if n == 1 else f"{n} {thing}s"


def refusal(website: str, api: str) -> str | None:
    """Why the look will not start on these addresses, or None. Each must be a test one on this
    machine, and the test API another address than the website: the look signs in on the test
    API itself, never through the website."""
    for what, url in (("website", website), ("test API", api)):
        parts = urlsplit(url)
        try:
            port = parts.port
        except ValueError:
            port = None
        if parts.hostname != LOCAL_HOST or port is None or port in LIVE_PORTS:
            return (
                f"The {what} must be a test one on this machine ({LOCAL_HOST}, its port named, "
                f"never 3000 or 8000), not {url}."
            )
    if urlsplit(website).port == urlsplit(api).port:
        return "The test API and the website must be two addresses: the look signs in on the API."
    return None


def _around(text: str, at: int) -> str:
    """The words either side of position `at`, on one line, the dashes written out."""
    return " ".join(written_out(text[max(0, at - AROUND) : at + AROUND + 1]).split())


def _first_line(error: object) -> str:
    said = str(getattr(error, "message", None) or error).strip()
    return said.splitlines()[0] if said else ""


class Look:
    """One look at the teacher's screens: what it read, and every problem it found."""

    def __init__(self, website: str, api: str, teacher: str, key: str, folder: Path) -> None:
        self.website = website
        self.api = api
        self.teacher = teacher
        self.key = key
        self.folder = folder
        self.pages: list[dict] = []
        self.problems: list[str] = []
        self.stopped: list[str] = []
        # Whether each research page the look tried with the key opened.
        self.research_opened: list[bool] = []
        self.research = "read with the research key" if key else "not opened: no research key set"

    def clean(self, text: str) -> str:
        """`text` as a problem may say it: its long dashes written out, and no key."""
        return hidden(written_out(text), self.key)

    def note(self, found: list[str], text: str) -> None:
        """Adds a problem to `found`, cleaned where it is made."""
        found.append(self.clean(text))

    def said(self, error: BaseException) -> str:
        """An error in a few words: its kind and its first line, never the key."""
        return self.clean(f"{type(error).__name__}: {_first_line(error)}")

    def run(self) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for size, width in WIDTHS:
                    self.at_width(browser, size, width)
            finally:
                browser.close()

    def at_width(self, browser, size: str, width: int) -> None:
        context = browser.new_context(
            viewport={"width": width, "height": HEIGHT}, service_workers="block"
        )
        try:
            card = self.sign_in(context, size)
            if card is None:
                return
            # From here on, a page can read and nothing else.
            context.route(lambda url: True, self.guard)
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(_first_line(error)))
            self.page_look(
                page,
                f"teacher-{size}",
                "/teacher",
                errors,
                lambda name, found: self.class_view(page, name, card, found),
            )
            self.research_pages(page, size, card, errors)
        except Exception as failure:
            self.note(
                self.problems, f"{size}: the look at this width stopped: {self.said(failure)}"
            )
        finally:
            context.close()

    def sign_in(self, context, size: str) -> dict | None:
        """Signs in on the test API itself, hands that sign-in to the browser for the website,
        and reads the teacher's screen through the website: the card on it, or None when the
        website does not reach the test API (a problem, and nothing is looked at)."""
        teacher = {"role": "teacher", "username": self.teacher, "password": PASSWORD}
        signed = context.request.post(f"{self.api}/api/auth/demo", data=teacher)
        if not signed.ok:
            self.note(
                self.problems, f"{size}: demo sign-in on the test API answered {signed.status}"
            )
            return None
        # Cookies on this machine are not kept apart by port; the website is given it outright
        # all the same.
        context.add_cookies(
            [
                {"name": c["name"], "value": c["value"], "url": self.website, "httpOnly": True}
                for c in context.cookies(self.api)
            ]
        )
        thread = context.request.get(f"{self.website}/api/teacher/thread")
        if not thread.ok:
            self.note(
                self.problems,
                f"{size}: signed in on the test API, the teacher's screen answered "
                f"{thread.status} through the website, so the website does not reach the test "
                "API and nothing was looked at",
            )
            return None
        return thread.json().get("showing") or {}

    def guard(self, route) -> None:
        """Lets a GET through, and stops anything else before it leaves the browser."""
        request = route.request
        if request.method == "GET":
            route.continue_()
        else:
            self.stopped.append(f"{request.method} {urlparse(request.url).path}")
            route.abort()

    def page_look(self, page, name: str, path: str, errors: list[str], read) -> bool:
        """Opens `path` and reads it with `read`, which says whether the page showed what it is
        for; then the checks every page gets, and its screenshots. Whatever goes wrong on the
        page is its own problem, and the look goes on with the next one."""
        found: list[str] = []
        shots: list[str] = []
        shown = False
        try:
            page.goto(f"{self.website}{path}")
            shown = bool(read(name, found))
            self.check(page, name, found)
        except Exception as failure:
            self.note(found, f"{name}: the look at this page stopped: {self.said(failure)}")
        try:
            shots = self.shoot(page, name)
        except Exception as failure:
            self.note(found, f"{name}: no screenshot: {self.said(failure)}")
        for error in errors:
            self.note(found, f"{name}: page error: {error}")
        errors.clear()
        self.pages.append({"name": name, "path": path, "problems": found, "screenshots": shots})
        self.problems += found
        return shown

    def class_view(self, page, name: str, card: dict, found: list[str]) -> bool:
        """Every pupil of the class on the class view. Wide, the view sits beside the
        conversation; on a phone it is behind its own tab, and pressing the tab only switches
        the view."""
        if card.get("type") != "class":
            shown = f"the {card['type']} card" if card.get("type") else "nothing"
            self.note(found, f"{name}: the teacher's screen shows {shown}, not the class view")
            self.wait(page.locator("main").first, name, "the page", found)
            return False
        panel, tab = page.locator("#panel-card"), page.locator("#tab-card")
        either = panel.or_(tab).filter(visible=True).first
        if not self.wait(either, name, "the class view or its tab", found):
            return False
        if tab.is_visible():
            if self.covered(page):
                self.note(found, f"{name}: the class view could not be opened: a dialog is over it")
                return False
            tab.click(timeout=WAIT_MS)
        students = panel.get_by_text("Students", exact=True).first
        if not self.wait(students, name, "the pupils", found):
            return False
        pupils = [s["pseudonym"] for s in card.get("students", [])]
        missing = missing_pupils(panel.inner_text(), pupils)
        if missing:
            self.note(
                found,
                f"{name}: {len(missing)} of {len(pupils)} pupils are not on the class view: "
                f"{', '.join(missing)}",
            )
        return True

    def research_pages(self, page, size: str, card: dict, errors: list[str]) -> None:
        if not self.key:
            self.page_look(
                page,
                f"research-{size}",
                "/research",
                errors,
                lambda name, found: self.wait(
                    page.get_by_label("Research key"), name, "the research key box", found
                ),
            )
            return
        view = page.get_by_role("heading", name="Research view")
        opened = self.page_look(
            page,
            f"research-{size}",
            "/research",
            errors,
            lambda name, found: self.open_with_key(page, name, view, found),
        )
        self.research_opened.append(opened)
        lesson = card.get("session_id") if card.get("type") == "class" else None
        if not (opened and lesson):
            return
        # Its own address, with the key typed again: a page opened afresh starts without it.
        students = page.get_by_role("heading", name="Every student")
        self.research_opened.append(
            self.page_look(
                page,
                f"lesson-{size}",
                f"/research?lesson={lesson}",
                errors,
                lambda name, found: self.open_with_key(page, name, students, found),
            )
        )

    def open_with_key(self, page, name: str, shown, found: list[str]) -> bool:
        """Types the key into the page's key box and opens it, until `shown` is on the page."""
        box = page.get_by_label("Research key")
        if not self.wait(box, name, "the research key box", found):
            return False
        box.fill(self.key)
        page.get_by_role("button", name="Open", exact=True).click()
        refused = page.get_by_text("That key was not accepted")
        if not self.wait(shown.or_(refused).first, name, "the research view", found):
            return False
        if refused.is_visible():
            self.note(found, f"{name}: the research key was not accepted")
            return False
        return True

    def wait(self, locator, name: str, what: str, found: list[str]) -> bool:
        """Whether `locator` shows within WAIT_MS; a problem when it does not."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        try:
            locator.wait_for(state="visible", timeout=WAIT_MS)
        except PlaywrightTimeout:
            self.note(found, f"{name}: {what} did not show within {WAIT_MS // 1000} s")
            return False
        return True

    def covered(self, page) -> bool:
        """Whether a dialog that must be answered first is over the page."""
        return page.locator(MODAL).filter(visible=True).count() > 0

    def check(self, page, name: str, found: list[str]) -> None:
        """The checks every page gets: what runs off the side, a dialog over it, long dashes."""
        wide = wide_things(page.evaluate(WIDE))
        for problem in page_problems(name, page.inner_text("body"), wide):
            self.note(found, problem)
        if self.covered(page):
            over = page.locator(MODAL).filter(visible=True).first.inner_text()
            self.note(found, f"{name}: a dialog covers the screen: {' '.join(over.split())[:80]}")

    def shoot(self, page, name: str) -> list[str]:
        """Screenshots of the page down the box it scrolls in, a screen at a time, so that all of
        a class of 30 is in them; one of the whole page when it scrolls itself."""
        box = page.evaluate_handle(SCROLL_BOX).as_element()
        if box is None:
            shot = f"{name}-1.png"
            page.screenshot(path=str(self.folder / shot), full_page=True)
            return [shot]
        height, total = box.evaluate("(el) => [el.clientHeight, el.scrollHeight]")
        shots: list[str] = []
        top = 0
        while True:
            box.evaluate("(el, top) => { el.scrollTop = top; }", top)
            shot = f"{name}-{len(shots) + 1}.png"
            box.screenshot(path=str(self.folder / shot))
            shots.append(shot)
            if top + height >= total or len(shots) == MOST_SHOTS:
                break
            top += max(1, height - OVERLAP)
        box.evaluate("(el) => { el.scrollTop = 0; }")
        return shots

    def report(self) -> dict:
        problems = list(self.problems)
        if self.stopped:
            problems.append(
                "the pages tried to send what is not a read, and it was stopped before it left "
                f"the browser: {', '.join(sorted(set(self.stopped)))}"
            )
        return {
            "passed": bool(self.pages) and not problems,
            "research_seen": bool(self.key and self.research_opened) and all(self.research_opened),
            "website": self.website,
            "api": self.api,
            "teacher": self.teacher,
            "research": self.research,
            "pages": [
                {**p, "problems": [self.clean(x) for x in p["problems"]]} for p in self.pages
            ],
            "problems": [self.clean(p) for p in problems],
            "stopped": sorted(set(self.stopped)),
        }


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print("Run: look.py <website> <api> <teacher> <folder>", file=sys.stderr)
        return 2
    website, api = argv[1].rstrip("/"), argv[2].rstrip("/")
    teacher, folder = argv[3], Path(argv[4])
    refused = refusal(website, api)
    if refused:
        print(refused, file=sys.stderr)
        return 2
    folder.mkdir(parents=True, exist_ok=True)
    look = Look(website, api, teacher, os.environ.get(KEY_ENV, ""), folder)
    try:
        look.run()
    except Exception as error:
        # Whatever stopped the look, look.json still says what it saw until then.
        look.note(look.problems, f"the look stopped: {look.said(error)}")
    report = look.report()
    text = hidden(json.dumps(report, indent=2), look.key)
    (folder / "look.json").write_text(text + "\n", encoding="utf-8")
    print("every check passed" if report["passed"] else counted(len(report["problems"]), "problem"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
