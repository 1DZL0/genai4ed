"""The report of a school day run: one page for the platform's owner to read, and to show a
professor if they choose, beside a JSON file of everything behind it.

The page, top to bottom:
- in a free run, a plain warning: a scripted stand-in played the tutor and the class agent, so
  every check whose result depends on what a model wrote means nothing. Those are listed on
  their own as informational and are not counted; only the checks on the platform's own
  workings (COUNTED_WHEN_FREE) count;
- how many checks passed, failed and did not come up;
- the cost, the models, the prompt versions, the parts that ran and the parts that did not;
- how many of the pupils' lines the writer could not write, so a stand-in line was sent
  instead, and why, counted by reason (the driver's "writer fell back" events);
- the failed checks, each opening to its evidence: the pupil, the lesson, what they said, the
  tutor's reply and a note;
- the checks that did not come up, each with the part of the day that reaches it. Such a check
  is never a pass;
- the passed checks;
- in a free run, the informational checks;
- the cost per part, per lesson and per pupil per lesson: each part's cost, from the key's
  balance before and after it, split over its lessons by the tutor's tokens in each;
- every lesson and, in it, every pupil's whole conversation with the tutor.

Every check shows, under its title, the line saying what it means. All text from the run is
escaped, so no pupil's or tutor's words can change the page. The page stands alone: its styles
are inline and it loads no file, script or font. It reads on a phone: nothing runs off the side,
and a wide table scrolls inside its own box.
"""

import html
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from bench.pupils import BEATS
from bench.school.checks import NOT_UP, PASS, Evidence, Result, judgment, sends_a_message
from bench.school.collect import LessonFacts, RunData, Turn
from bench.school.driver import FELL_BACK, Sent
from bench.school.lessons import GROUP_LESSONS, PART_ONE
from bench.school.teacher import Drafted

# In a free run a scripted stand-in plays the tutor and the class agent and writes the lesson
# summaries, so a check whose result depends on what a model wrote means nothing there: it is
# informational, not counted. Only these checks, on the platform's own workings, count. Codes
# are matched whole, so C1 is not C12.
COUNTED_WHEN_FREE = frozenset(
    {
        *("S1", "S2", "S3", "S5"),
        *("U1", "U2", "U3", "U4", "U5", "U6", "U7"),
        *("C6", "C7", "C8", "C9", "C12", "C14"),
        *("X1", "X2", "X3", "R1", "M4", "M5"),
    }
)


def _places() -> dict[str, tuple[str, str]]:
    """Each lesson of the day by its key: its part, and how the page names where it sits."""
    places = {PART_ONE.key: ("1", "Part 1")}
    for group, plans in GROUP_LESSONS.items():
        for n, plan in enumerate(plans, start=1):
            places[plan.key] = ("2", f"Part 2, Group {group}, lesson {n}")
    return places


PLACES = _places()
# The files each lesson's teacher attaches while drafting it. A lesson set up from an earlier
# run's brief is not drafted, so its tutor was given none of them.
ATTACHED = {
    plan.key: plan.attachments
    for plan in (PART_ONE, *(p for plans in GROUP_LESSONS.values() for p in plans))
}

# For a check that did not come up: the parts of the day that reach its moment, and how to say
# so. Read from the cast (cast.py), the lessons (lessons.py) and the runner's plan. Part 1 is the
# full class: its tricks, upset and ask-teacher pupils, late joiners, signing back in, double
# tap and disclosure, and the teacher's moves during and after the lesson. Part 2's groups take
# several lessons (memory), and hold the go gently note, the guidance, the same questions, the
# other help rules, the attached texts and files, the paragraph request, the pasted block, the
# jump, the phone number and the memory settings; the privacy probes run after it.
_EITHER, _ONE, _TWO = ("1", "2"), ("1",), ("2",)
REACHED_BY: dict[str, tuple[tuple[str, ...], str]] = {
    "T1": (_EITHER, "either part"),
    "T2": (_EITHER, "either part"),
    "T3": (_EITHER, "either part"),
    "T4": (_EITHER, "either part"),
    "T5": (_EITHER, "Part 1, or Part 2's Group B"),
    "T6": (_TWO, "Part 2, Group A or B, whose pupils take more than one lesson"),
    "T7": (_ONE, "Part 1"),
    "T8": (_EITHER, "either part; Part 2 brings English, history and science"),
    "T9": (_ONE, "Part 1"),
    "T10": (_TWO, "Part 2, Group B"),
    "T11": (_TWO, "Part 2, Groups B and C"),
    "T12": (_TWO, "Part 2, Group A"),
    "P1": (_EITHER, "either part"),
    "P2": (_EITHER, "either part"),
    "P3": (_EITHER, "either part"),
    "P4": (_EITHER, "either part"),
    "P5": (_EITHER, "either part"),
    "P6": (_TWO, "Part 2, Group C"),
    "P7": (_TWO, "Part 2, Group A"),
    "P8": (_TWO, "Part 2, Group A"),
    "M1": (_TWO, "Part 2, Group A or B"),
    "M2": (_TWO, "Part 2, Group A"),
    "M3": (_EITHER, "either part"),
    "M4": (_TWO, "Part 2, Group B"),
    "M5": (_TWO, "Part 2, Group C"),
    "C1": (_EITHER, "either part, with the lessons drafted rather than saved"),
    "C2": (_TWO, "Part 2, Groups A and C, with the lessons drafted rather than saved"),
    "C3": (_TWO, "Part 2, Group A"),
    "C4": (_EITHER, "either part"),
    "C5": (_ONE, "Part 1"),
    "C6": (_ONE, "Part 1"),
    "C7": (_ONE, "Part 1"),
    "C8": (_ONE, "Part 1"),
    "C9": (_ONE, "Part 1"),
    "C10": (_TWO, "Part 2, Group B or C"),
    "C11": (_ONE, "Part 1"),
    "C12": (_TWO, "Part 2, Group B"),
    "C13": (_ONE, "Part 1"),
    "C14": (_ONE, "Part 1"),
    "U1": (_EITHER, "either part"),
    "U2": (_EITHER, "either part"),
    "U3": (_ONE, "Part 1"),
    "U4": (_ONE, "Part 1"),
    "U5": (_ONE, "Part 1"),
    "U6": (_TWO, "Part 2, Group A"),
    "U7": (_TWO, "Part 2, Group B"),
    "S1": (_EITHER, "either part"),
    "S2": (_EITHER, "either part"),
    "S3": (_ONE, "Part 1"),
    "S4": (_EITHER, "either part"),
    "S5": (_ONE, "Part 1, with the test website running at 127.0.0.1:3002"),
    "X1": (_TWO, "Part 2, Groups A and B"),
    "X2": (_TWO, "Part 2, Groups A and B"),
    "X3": (_TWO, "Part 2, Groups A and B"),
    "R1": (_EITHER, "either part, with the research key set"),
}
# For a check the list does not name.
_ANY = (_EITHER, "the whole day again")

# Who a pupil of the cast is, in plain words, from what the driver says of them.
_KINDS = {
    "strong": "a strong pupil",
    "average": "an average pupil",
    "struggling": "a pupil who finds it hard",
    "quiet": "a quiet pupil",
    "off_task": "a pupil who drifts off task",
    "trick": "a pupil who tries to talk the tutor round",
    "upset": "a pupil worried about a test",
    "ask_teacher": "a pupil who would rather ask the teacher",
    "copier": "a pupil who copies a classmate",
    "leaver": "a pupil who leaves a step for later",
}
_STEERS = {
    "slow": "who gets there slowly",
    "out_of_reach": "who is out of reach of a harder question",
    "recovers": "who struggles, then recovers",
}
_FLAGS = {
    "eal": "learning English",
    "joins_after_s": "joins late",
    "signs_back_in": "signs out and back in",
    "note_target": "the teacher's go gently note is about them",
    "guide_target": "the teacher's guidance is about them",
}

# What each of the pupils' moves was meant to be, in plain words.
_MOVES = {
    "open": "opened the lesson",
    "signed_back_in": "signed back in and opened the page",
    "ask_teacher": "pressed Ask my teacher",
    "helped": "tapped to say the reply helped",
    "leave": "left the step for later",
    "come_back": "came back to the step",
    "jump": "moved to another part",
    "button:dont_understand": "pressed: I don't understand",
    "button:another_way": "pressed: can you explain that another way",
    "button:example": "pressed: can you give me an example",
    "button:why_wrong": "pressed: why is my answer wrong",
    "right": "a right answer",
    "right_why": "a right answer with a reason",
    "bare_right": "a bare right answer",
    "how": "how they worked it out",
    "wrong": "a wrong answer from a slip",
    "bare_wrong": "a bare wrong answer",
    "confident_wrong": "a confident wrong answer",
    "copied_wrong": "a wrong answer copied from a classmate",
    "double_tap": "a wrong answer sent twice at once",
    "not_sure": "not sure",
    "what_mean": "asking what the question means",
    "one_word": "a one word reply",
    "off_topic": "off topic",
    "ask_answer": "a trick, asking to be told the answer",
    "teacher_said": "a trick, saying the teacher allows the answer",
    "ignore_rules": "a trick, telling the tutor to ignore its rules",
    "what_remember": "asking what the tutor remembers about them",
    "stressed": "worried about a test",
    "cant_do": "saying they cannot do it",
    "closer": "a little closer to the answer",
    "no_movement": "nothing new",
    "disclosure": "saying someone keeps pushing them around",
    "personal_details": "a made-up phone number",
    "write_it_for_me": "asking the tutor to write it for them",
    "long_paste": "a long block of pasted text",
    "greek": "a message in Greek",
}

# The tutor's judgment of what a pupil said, and its pitch call, in plain words.
_MARKS = {
    "met": "The tutor marked it right",
    "partial": "The tutor marked it partly right",
    "not_met": "The tutor marked it not right",
    "unclear": "The tutor could not tell whether it was right",
}
_PITCHES = {
    "as written": "asked the step as written",
    "stretched": "asked a harder version",
    "more support": "gave more help up front",
    "stayed": "stayed with its harder version",
    "let go": "went back to the step as written",
}

# Why a pupil's request was refused, as the driver notes a refusal in the log's events
# (driver.py: _Answer.outcome), each noted at the time the refused request went.
_REFUSALS = {
    "paused": "refused: the lesson was paused",
    "time up": "refused: the lesson's time was up",
    "closed": "refused: the lesson was closed",
    "rate limited": "refused: a reply was still on its way, or the day's turns were used up",
    "unavailable": "refused: the tutor was not available",
}
# Why a request got no answer, by its status alone, when the events say nothing of it.
_REFUSED = {
    0: "no answer came",
    409: "refused: the lesson was paused, closed or out of time",
    429: _REFUSALS["rate limited"],
    503: _REFUSALS["unavailable"],
}

# How each outcome reads on a check's tag, and the style it takes.
_TAGS = {PASS: ("pass", "Passed"), NOT_UP: ("notup", "Did not come up")}
_FAILED_TAG = ("fail", "Failed")
_OUTCOME_WORDS = {PASS: "passed", NOT_UP: "did not come up"}


def render(results: list[Result], data: RunData, meta: dict) -> str:
    """The report's page for a run, as one self-contained HTML document.

    `meta` holds the run's `date`; `parts_run` and `parts_not_run`, lists of part names ("1",
    "2"), the second also taken as a dict of name to why; `models` and `prompt_versions`, as
    text, a list, or a dict of what to what; `cost`, the dollars spent in all; `cost_by_part`,
    part name to dollars, from the key's balance before and after the part; and `free`, true
    for a free practice run. Anything missing reads as not recorded."""
    return _Page(results, data, meta).html()


def save(folder: Path, results: list[Result], data: RunData, meta: dict) -> Path:
    """Writes the run's results, meta and data to results.json, then the page to report.html,
    both in `folder` (made if missing), and returns the page's path. The JSON goes first, so a
    page that fails to render loses nothing of the run. A value JSON does not take as it is,
    such as a date, is written as text."""
    folder.mkdir(parents=True, exist_ok=True)
    raw = {"meta": meta, "results": [asdict(r) for r in results], "data": asdict(data)}
    (folder / "results.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    page = folder / "report.html"
    page.write_text(render(results, data, meta), encoding="utf-8")
    return page


@dataclass
class _Share:
    """A lesson's part in its part's cost: the tutor's tokens in it and the pupils who took
    part; its share of the part's cost and that cost, or None and why when it is not split."""

    tokens: int
    pupils: int
    share: float | None = None
    cost: float | None = None
    why: str = ""

    @property
    def per_pupil(self) -> float | None:
        return self.cost / self.pupils if self.cost is not None and self.pupils else None


# Why a lesson's cost is not shown, as its row in the cost table says it, and as a sentence in
# the lesson's own section. A lesson the tutor replied in with no tokens recorded is not free:
# its cost is not known.
_NO_TOKENS = "tokens not recorded"
_COST_NOT_KNOWN = {
    "not recorded": "Cost: not recorded.",
    "part not known": "Cost: not known, as this lesson is not one of the day's parts.",
    _NO_TOKENS: "Cost: not known, as the tutor's tokens were not recorded in this lesson.",
}


class _Page:
    """The page for one run, with what it needs worked out once."""

    def __init__(self, results: list[Result], data: RunData, meta: dict) -> None:
        self.data = data
        self.meta = meta
        self.free = bool(meta.get("free"))
        self.not_run = set(_names(meta.get("parts_not_run")))
        counted = [r for r in results if not self._informational(r)]
        self.passed = [r for r in counted if r.outcome == PASS]
        self.not_up = [r for r in counted if r.outcome == NOT_UP]
        # Anything else is listed as failed: an outcome is never hidden or taken for a pass.
        self.failed = [r for r in counted if r.outcome not in (PASS, NOT_UP)]
        self.informational = [r for r in results if self._informational(r)]
        self.lessons = _lessons(data)
        self.labels = {f.key: _label(f) for f in self.lessons}
        self.pupils = {f.key: _pupils_in(data, f.session_id) for f in self.lessons}
        self.anchors = {
            (f.key, pupil): f"lesson-{i}-pupil-{j}"
            for i, f in enumerate(self.lessons, start=1)
            for j, pupil in enumerate(self.pupils[f.key], start=1)
        }
        spent = meta.get("cost_by_part")
        self.by_part = (
            {str(k): _amount(v) for k, v in spent.items()} if isinstance(spent, dict) else {}
        )
        self.shares, self.split_notes = _split(self.lessons, data, self.pupils, self.by_part)
        # The evidence of the failed checks that count: by lesson, by pupil in a lesson, and by
        # the turn it shows, to mark the turns behind them in the conversations. A turn is known
        # by what the pupil said as well as the reply: a reply held back shows the platform's
        # fixed holding line, so the reply alone would mark every held-back turn of the pupil.
        self.failed_in: dict[str, Counter[str]] = {}
        self.failed_for: dict[tuple[str, str], list[str]] = {}
        self.behind: dict[tuple[str, str, str, str], list[str]] = {}
        for result in self.failed:
            for item in result.evidence:
                self.failed_in.setdefault(item.lesson, Counter())[result.code] += 1
                _add(self.failed_for.setdefault((item.lesson, item.pupil), []), result.code)
                if item.reply:
                    key = (item.pupil, item.lesson, item.said, item.reply)
                    _add(self.behind.setdefault(key, []), result.code)
        # Why each refused request was refused, as the driver noted it in the events: by pupil,
        # move and the time the request went, which the request and its note share.
        self.refusals: dict[tuple[str, str, str], str] = {}
        for event in data.events:
            what = event.get("what") if isinstance(event, dict) else None
            if isinstance(what, str) and what in _REFUSALS:
                when = (str(event.get("pupil")), str(event.get("beat")), str(event.get("at")))
                self.refusals[when] = what

    def _informational(self, result: Result) -> bool:
        return self.free and result.code not in COUNTED_WHEN_FREE

    def html(self) -> str:
        day = _day(self.meta.get("date"))
        title = f"School day report: {day}" if day else "School day report"
        when = f", run on {day}" if day else ""
        parts = [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_e(title)}</title>",
            f"<style>{_STYLE}</style>",
            "</head>",
            "<body>",
            "<main>",
            "<h1>School day report</h1>",
            f'<p class="muted">A rehearsal of a school day on a copy of the platform{_e(when)}. '
            "Every check was worked out from the platform's own records: no model judged the "
            "tutor.</p>",
            self._banner(),
            self._counts(),
            self._facts(day),
            self._stand_ins(),
            self._contents(),
            self._section(
                "failed",
                "Failed",
                "Each failed check opens to what it found: the pupil's and the tutor's words as "
                "the platform kept them.",
                self.failed,
            ),
            self._section(
                "not-up",
                "Did not come up",
                "The moment each of these checks needs never happened in this run, so it says "
                "nothing either way. None of them counts as a pass. Each says which part of the "
                "day reaches it.",
                self.not_up,
            ),
            self._section("passed", "Passed", "", self.passed),
        ]
        if self.free:
            parts.append(
                self._section(
                    "informational",
                    "Informational in a free run",
                    "A scripted stand-in played the tutor and the class agent, so these "
                    "results, which depend on what a model wrote, mean nothing. They are kept "
                    "for the record and not counted.",
                    self.informational,
                )
            )
        parts += [self._cost(), self._all_lessons(), "</main>", "</body>", "</html>"]
        return "\n".join(part for part in parts if part) + "\n"

    # ---------- the top ----------

    def _banner(self) -> str:
        if not self.free:
            return ""
        return (
            '<p class="banner"><strong>A free practice run.</strong> A scripted stand-in played '
            "the tutor and the class agent instead of a real model, so every check whose result "
            "depends on what a model wrote means nothing here. Those checks are listed after "
            "the passed checks, as informational, and are not counted. Only the checks on the "
            "platform's own workings count: errors and speed, the pupils' buttons and pages, the "
            "teacher's controls, files, privacy, the research pages and the memory settings.</p>"
        )

    def _counts(self) -> str:
        counts = [
            ("pass", len(self.passed), "passed"),
            ("fail", len(self.failed), "failed"),
            ("notup", len(self.not_up), "did not come up"),
        ]
        if self.free:
            counts.append(("info", len(self.informational), "informational, not counted"))
        shown = "".join(
            f'<span class="{style}"><strong>{n}</strong> {words}</span>'
            for style, n, words in counts
        )
        lead = "<span>Counted:</span>" if self.free else ""
        return f'<p class="counts">{lead}{shown}</p>'

    def _facts(self, day: str) -> str:
        meta = self.meta
        total, missing = self._total()
        if self.free:
            cost = "Nothing: a free practice run."
        elif total is None:
            cost = "not recorded"
        else:
            whole = "" if missing else " in all"
            cost = f'{_e(self._total_said())}{whole} (<a href="#cost">the cost in detail</a>)'
        errors = self.data.errors
        problems = "none"
        if errors:
            listed = "".join(f"<li>{_e(error)}</li>" for error in errors)
            problems = (
                f"{len(errors)}<details><summary>Show them</summary>"
                f'<ul class="plain">{listed}</ul></details>'
            )
        rows = [
            ("Run on", _e(day or "not recorded")),
            ("Cost", cost),
            ("Models", _e(_listed(meta.get("models")))),
            ("Prompt versions", _e(_listed(meta.get("prompt_versions")))),
            ("Parts run", _e(_parts(meta.get("parts_run")))),
            ("Parts that did not run", _e(_parts(meta.get("parts_not_run")))),
            ("Problems the run logged", problems),
        ]
        shown = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in rows)
        return f'<dl class="facts">{shown}</dl>'

    def _stand_ins(self) -> str:
        """How many of the pupils' lines the writer could not write, so the move's stand-in
        line was sent, of all the lines it was asked for, and why, counted by reason: "" when
        it was asked for none."""
        written, stand_ins = _writer_lines(self.data.sent)
        if not written:
            return ""
        lead = "Pupil lines the writer could not write, so a stand-in line was sent:"
        if not stand_ins:
            return f"<p>{lead} none of {written}.</p>"
        whys = Counter(
            _why(event.get("why"))
            for event in self.data.events
            if isinstance(event, dict) and event.get("what") == FELL_BACK
        )
        # A run logged before the driver kept the reasons still counts its stand-ins.
        unknown = stand_ins - sum(whys.values())
        if unknown > 0:
            whys[_NO_REASON] += unknown
        said = "; ".join(f"{why}: {n}" for why, n in whys.most_common())
        return f"<p>{lead} {stand_ins} of {written} ({_e(said)}).</p>"

    def _total(self) -> tuple[float | None, list[str]]:
        """The dollars spent, and the parts that ran with no cost recorded. When every part
        that ran has its cost, the dollars are meta's cost, else the parts' costs added up: the
        whole. When a part is missing, nothing recorded is the whole, so the dollars are the
        most the record shows, which the page gives as "at least". None when nothing shows."""
        given = _amount(self.meta.get("cost"))
        known = [v for v in self.by_part.values() if v is not None]
        added = sum(known) if known else None
        missing = [p for p in _names(self.meta.get("parts_run")) if self.by_part.get(p) is None]
        if missing:
            figures = [f for f in (given, added) if f is not None]
            return (max(figures) if figures else None), missing
        return (given if given is not None else added), []

    def _total_said(self) -> str:
        """The dollars spent as the page says them: "$17.40", "at least $0.40 (Part 1 not
        recorded)", or "not recorded"."""
        total, missing = self._total()
        if total is None:
            return "not recorded"
        if missing:
            parts = _and([f"Part {part}" for part in missing])
            return f"at least {_dollars(total)} ({parts} not recorded)"
        return _dollars(total)

    def _contents(self) -> str:
        links = [
            ("failed", f"Failed ({len(self.failed)})"),
            ("not-up", f"Did not come up ({len(self.not_up)})"),
            ("passed", f"Passed ({len(self.passed)})"),
        ]
        if self.free:
            links.append(("informational", f"Informational ({len(self.informational)})"))
        links += [("cost", "Cost"), ("lessons", "Lessons and pupils")]
        shown = "".join(f'<a href="#{anchor}">{words}</a>' for anchor, words in links)
        return f'<nav class="toc">On this page: {shown}</nav>'

    # ---------- the checks ----------

    def _section(self, anchor: str, heading: str, intro: str, results: list[Result]) -> str:
        checks = "".join(self._check(r) for r in results) or '<p class="muted">None.</p>'
        lead = f"<p>{intro}</p>" if intro else ""
        return f'<section id="{anchor}"><h2>{heading} ({len(results)})</h2>{lead}{checks}</section>'

    def _check(self, result: Result) -> str:
        if self._informational(result):
            style, word = "info", f"Informational: {_OUTCOME_WORDS.get(result.outcome, 'failed')}"
        else:
            style, word = _TAGS.get(result.outcome, _FAILED_TAG)
        parts = [
            '<article class="check">',
            f'<h3><span class="tag {style}">{_e(word)}</span>'
            f'<span class="code">{_e(result.code)}</span> {_e(result.title)}</h3>',
            f'<p class="meaning">{_e(result.meaning)}</p>',
            _detail(result.detail),
        ]
        if result.outcome == NOT_UP:
            parts.append(self._reach(result.code))
        if result.evidence:
            parts.append(self._evidence(result.evidence))
        parts.append("</article>")
        return "".join(parts)

    def _reach(self, code: str) -> str:
        """Which part of the day reaches a check that did not come up, and whether it ran."""
        parts, where = REACHED_BY.get(code, _ANY)
        said = f"To reach it, run {where}."
        if all(part in self.not_run for part in parts):
            said += (
                f" Part {parts[0]} did not run this time."
                if len(parts) == 1
                else " Neither part ran this time."
            )
        return f'<p class="reach">{_e(said)}</p>'

    def _evidence(self, items: list[Evidence]) -> str:
        shown = []
        for item in items:
            fields = [
                ("Pupil", self._pupil_named(item.lesson, item.pupil)),
                ("Lesson", _e(self.labels.get(item.lesson, item.lesson))),
                ("What they said", _words(item.said)),
                ("The tutor's reply", _words(item.reply)),
                ("Note", _e(item.note)),
            ]
            rows = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in fields if value)
            shown.append(f'<li><dl class="item">{rows}</dl></li>')
        return (
            f"<details><summary>Show what it found ({len(items)})</summary>"
            f'<ol class="evidence">{"".join(shown)}</ol></details>'
        )

    def _pupil_named(self, lesson: str, pupil: str) -> str:
        """A pupil in a check's evidence: their pseudonym, who they are in the cast, and a link
        to their whole conversation in that lesson."""
        if not pupil:
            return ""
        shown = _e(pupil)
        who = _who(self.data.cast.get(pupil))
        if who:
            shown += f' <span class="muted">({_e(who)})</span>'
        anchor = self.anchors.get((lesson, pupil))
        if anchor:
            shown += f' <a href="#{anchor}">the whole conversation</a>'
        return shown

    # ---------- the cost ----------

    def _cost(self) -> str:
        if self.free:
            body = "<p>A free practice run: nothing was spent on models.</p>"
            return f'<section id="cost"><h2>Cost</h2>{body}</section>'
        intro = (
            "<p>What a part cost is how far the key's balance fell while it ran. The tutor, the "
            "class agent, the lesson summaries and the writer of the pupils' lines all spend "
            "from that key. Each part's cost is split over its lessons by how many tokens the "
            "tutor used in each; a token is a short piece of a word that a model reads or "
            "writes. A lesson's cost per pupil is its cost divided by the pupils who took "
            "part.</p>"
        )
        names = sorted(
            {
                *_names(self.meta.get("parts_run")),
                *self.by_part,
                *(part for f in self.lessons if (part := _part_of(f.key)) is not None),
            }
        )
        rows = []
        for name in names:
            ran = [f for f in self.lessons if _part_of(f.key) == name and f.session_id]
            spent = self.by_part.get(name)
            said = _dollars(spent)
            if spent is None and name in self.not_run:
                said = "did not run"
            tokens = sum(self.shares[f.key].tokens for f in ran)
            rows.append([f"Part {name}", said, str(len(ran)), f"{tokens:,}"])
        ran = [f for f in self.lessons if f.session_id]
        tokens = sum(self.shares[f.key].tokens for f in ran)
        rows.append(["In all", self._total_said(), str(len(ran)), f"{tokens:,}"])
        parts = _table(
            ["Part", "Spent", "Lessons that ran", "Tutor tokens"], rows, numbers=(1, 2, 3)
        )
        notes = list(self.split_notes)
        if not any(v is not None for v in self.by_part.values()):
            notes.append(
                "The cost of each part was not recorded, so it is not split over its lessons."
            )
        noted = "".join(f'<p class="note">{_e(note)}</p>' for note in notes)
        # The money comes straight after the lesson, so a phone shows it without scrolling.
        per_lesson = []
        for facts in self.lessons:
            share = self.shares[facts.key]
            took_part = str(share.pupils) if facts.session_id else ""
            tokens = f"{share.tokens:,}" if facts.session_id else ""
            if share.why == _NO_TOKENS:
                tokens = "not recorded"
            if share.cost is None:
                per_lesson.append([self.labels[facts.key], share.why, took_part, "", tokens, ""])
                continue
            per_pupil = _dollars(share.per_pupil) if share.pupils else "no pupils"
            shared = f"{share.share or 0:.0%}"
            per_lesson.append(
                [self.labels[facts.key], _dollars(share.cost), took_part, per_pupil, tokens, shared]
            )
        lessons = _table(
            ["Lesson", "Cost", "Pupils", "Cost per pupil", "Tutor tokens", "Share of its part"],
            per_lesson,
            numbers=(1, 2, 3, 4, 5),
        )
        return (
            f'<section id="cost"><h2>Cost</h2>{intro}{parts}{noted}'
            f"<h3>Per lesson and per pupil</h3>{lessons}</section>"
        )

    # ---------- the lessons and pupils ----------

    def _all_lessons(self) -> str:
        intro = (
            "<p>Every lesson of the run and, in each, every pupil's whole conversation with the "
            "tutor, as the platform kept it. Each conversation is open; close one to skip past "
            "it.</p>"
        )
        lessons = "".join(self._lesson(i, f) for i, f in enumerate(self.lessons, start=1))
        lessons = lessons or '<p class="muted">No lesson ran.</p>'
        return f'<section id="lessons"><h2>Lessons and pupils</h2>{intro}{lessons}</section>'

    def _lesson(self, number: int, facts: LessonFacts) -> str:
        about = [
            f"Taught by {facts.teacher}" if facts.teacher else "",
            _count(facts.steps, "step") if facts.steps else "",
            _drafted(facts.drafted),
        ]
        parts = [
            f'<article class="lesson" id="lesson-{number}">',
            f"<h3>{_e(self.labels[facts.key])}</h3>",
            f'<p class="muted">{_e(". ".join(filter(None, about)))}.</p>',
        ]
        if not facts.session_id:
            parts += ["<p>This lesson did not run.</p>", "</article>"]
            return "".join(parts)
        files = ATTACHED.get(facts.key) or []
        if facts.drafted is None and files:
            parts.append(
                "<p>Set up from an earlier run's brief, so its files "
                f"({_e(', '.join(files))}) were not given to the tutor: every reply in it was "
                "made without them.</p>"
            )
        turns = [t for t in self.data.turns if t.session_id == facts.session_id]
        pupils = self.pupils[facts.key]
        replies = sum(t.agent_line_id is not None for t in turns)
        took_part = (
            f"{_count(len(pupils), 'pupil')} took part, with "
            f"{_count(replies, 'reply', 'replies')} from the tutor."
        )
        if turns:
            models = ", ".join(sorted({t.model for t in turns if t.model})) or "not recorded"
            versions = ", ".join(sorted({t.prompt_version for t in turns if t.prompt_version}))
            took_part += (
                f" The tutor ran as {models}, with prompt version {versions or 'not recorded'}."
            )
        parts.append(f"<p>{_e(took_part)}</p>")
        if not self.free:
            parts.append(f"<p>{_e(self._lesson_cost(self.shares[facts.key]))}</p>")
        failed = self.failed_in.get(facts.key)
        if failed:
            said = ", ".join(f"{code} ({n})" for code, n in failed.items())
            parts.append(
                f'<p class="flag">Failed checks with evidence in this lesson: {_e(said)}.</p>'
            )
        if pupils:
            links = ", ".join(
                f'<a href="#{self.anchors[(facts.key, pupil)]}">{_e(pupil)}</a>' for pupil in pupils
            )
            parts.append(f'<p class="muted">Pupils: {links}</p>')
        parts += [self._pupil(facts, pupil) for pupil in pupils]
        parts.append("</article>")
        return "".join(parts)

    @staticmethod
    def _lesson_cost(share: _Share) -> str:
        if share.cost is None:
            return _COST_NOT_KNOWN.get(share.why, f"Cost: {share.why}.")
        if not share.pupils:
            return f"Cost: {_dollars(share.cost)} for the lesson."
        return f"Cost: {_dollars(share.cost)} for the lesson, {_dollars(share.per_pupil)} a pupil."

    def _pupil(self, facts: LessonFacts, pupil: str) -> str:
        """One pupil's whole conversation in a lesson, under a line saying who they are: each of
        the tutor's turns, with what the pupil said or did to get it, and what else they did
        between turns. It is open, so a link to it lands on the conversation itself; the reader
        can close it."""
        turns = [
            t for t in self.data.turns if t.session_id == facts.session_id and t.pupil == pupil
        ]
        requests = [
            s for s in self.data.sent if s.session_id == facts.session_id and s.pupil == pupil
        ]
        own, after = _placed(turns, requests)
        replies = sum(t.agent_line_id is not None for t in turns)
        about = ", ".join(
            filter(None, [_who(self.data.cast.get(pupil)), _count(replies, "reply", "replies")])
        )
        summary = (
            f"<strong>{_e(pupil or 'a pupil the run does not name')}</strong> "
            f'<span class="muted">{_e(about)}</span>'
        )
        codes = self.failed_for.get((facts.key, pupil))
        if codes:
            summary += f' <span class="flag">{_e(_behind(codes))}</span>'
        body = [self._actions(after.get(None, []))]
        for turn in turns:
            body += [
                self._turn(turn, own.get(turn.id), facts.key),
                self._actions(after.get(turn.id, [])),
            ]
        anchor = self.anchors[(facts.key, pupil)]
        return (
            f'<details class="pupil" id="{anchor}" open><summary>{summary}</summary>'
            f"{''.join(body)}</details>"
        )

    def _turn(self, turn: Turn, request: Sent | None, lesson: str) -> str:
        rows = []
        guidance = turn.request.get("guidance")
        if guidance:
            rows.append(("The teacher's guidance", _words(str(guidance))))
        if turn.said:
            rows.append(("Pupil", _words(turn.said)))
        elif request is not None:
            rows.append(("Pupil", f'<span class="muted">({_e(_move(request.beat))})</span>'))
        if turn.agent_line_id is None:
            rows.append(("Tutor", '<span class="muted">No reply: the model gave no answer.</span>'))
        else:
            rows.append(("Tutor", _words(turn.reply_text)))
        shown = "".join(f'<p><span class="who">{name}</span>{value}</p>' for name, value in rows)
        notes = _notes(turn, request)
        if notes:
            shown += f'<p class="note">{_e(". ".join(notes))}.</p>'
        codes = self._behind_turn(turn, request, lesson)
        if codes:
            shown += f'<p class="flag">{_e(_behind(codes))}</p>'
        return f'<div class="turn">{shown}</div>'

    def _behind_turn(self, turn: Turn, request: Sent | None, lesson: str) -> list[str]:
        """The failed checks whose evidence is this turn: the same pupil, lesson, reply and
        words from the pupil. A check's evidence gives the pupil's words as the platform kept
        them, else as the run sent them, so both are tried."""
        if not turn.reply_text:
            return []
        for said in dict.fromkeys([turn.said, request.text if request is not None else ""]):
            codes = self.behind.get((turn.pupil, lesson, said, turn.reply_text))
            if codes:
                return codes
        return []

    def _actions(self, requests: Iterable[Sent]) -> str:
        """What a pupil did between the tutor's turns, as a list: the requests that wrote no
        line of their own. A refused one says why, from the driver's note of it when there is
        one, else from its status."""
        shown = []
        for request in requests:
            words = _move(request.beat)
            if request.text and sends_a_message(request.beat):
                said = f'Sent "{request.text}", meant as: {words}'
            else:
                said = words[:1].upper() + words[1:]
            if request.status != 200:
                noted = self.refusals.get((request.pupil, request.beat, request.at))
                said += f" ({_REFUSALS[noted] if noted else _refused(request.status)})"
            shown.append(f"<li>{_e(said)}</li>")
        return f'<ul class="actions">{"".join(shown)}</ul>' if shown else ""


# ---------- reading the run ----------


def _lessons(data: RunData) -> list[LessonFacts]:
    """The run's lessons, then one for each lesson the run has records of but did not list, so
    that no conversation is left out."""
    listed = {f.session_id for f in data.lessons}
    seen = [t.session_id for t in data.turns] + [s.session_id for s in data.sent]
    stray = [s for s in dict.fromkeys(seen) if s and s not in listed]
    return [*data.lessons, *(LessonFacts(s, s, "", None, 0, {}, {}, "", None) for s in stray)]


def _part_of(key: str) -> str | None:
    """The part of the day a lesson belongs to, by its key; None for a lesson the day has not."""
    return PLACES[key][0] if key in PLACES else None


def _pupils_in(data: RunData, session_id: str) -> list[str]:
    """The pupils who took part in a lesson: everyone with a turn or a request in it, in the
    cast's order, then anyone the cast does not name in the order they came."""
    if not session_id:
        return []
    found = dict.fromkeys(
        [t.pupil for t in data.turns if t.session_id == session_id]
        + [s.pupil for s in data.sent if s.session_id == session_id]
    )
    order = {pupil: n for n, pupil in enumerate(data.cast)}
    return sorted(found, key=lambda pupil: order.get(pupil, len(order)))


def _tokens(turn: Turn) -> int:
    """The tokens the model reported for a turn, as the platform counts them; none when it
    reported none."""
    total = (turn.usage or {}).get("total_tokens")
    if isinstance(total, bool) or not isinstance(total, int | float):
        return 0
    return int(total)


def _split(
    lessons: list[LessonFacts],
    data: RunData,
    pupils: dict[str, list[str]],
    by_part: dict[str, float | None],
) -> tuple[dict[str, _Share], list[str]]:
    """Each lesson's share of its part's cost, by the tutor's tokens in it, with a note on each
    cost not split that way:
    - a part with no lesson listed is not split;
    - a part whose lessons used no tokens at all is split evenly over those that ran;
    - a part none of whose lessons ran is not split;
    - a lesson the tutor replied in with no tokens recorded, beside lessons of its part that
      recorded them, gets no share: its cost is not known, and is never shown as nothing."""
    tokens: Counter[str] = Counter()
    replied: set[str] = set()
    for turn in data.turns:
        tokens[turn.session_id] += _tokens(turn)
        if turn.agent_line_id is not None:
            replied.add(turn.session_id)
    parts: dict[str | None, list[LessonFacts]] = {}
    for facts in lessons:
        parts.setdefault(_part_of(facts.key), []).append(facts)
    shares: dict[str, _Share] = {}
    notes: list[str] = [
        f"Part {part} cost {_dollars(spent)}, but no lesson of it is listed, so its cost could "
        "not be split."
        for part, spent in sorted(by_part.items())
        if spent is not None and part not in parts
    ]
    for part, members in parts.items():
        spent = by_part.get(part) if part is not None else None
        ran = [f for f in members if f.session_id]
        used = sum(tokens[f.session_id] for f in ran)
        if spent is not None and ran and not used:
            notes.append(
                f"No tokens were recorded for Part {part}, so its cost is split evenly over its "
                f"{_count(len(ran), 'lesson')} that ran."
            )
        if spent is not None and not ran:
            notes.append(
                f"None of Part {part}'s lessons ran, so its cost of {_dollars(spent)} is not split."
            )
        for facts in members:
            if not facts.session_id:
                shares[facts.key] = _Share(0, 0, why="did not run")
                continue
            share = _Share(tokens[facts.session_id], len(pupils[facts.key]))
            if part is None:
                share.why = "part not known"
            elif spent is None:
                share.why = "not recorded"
            elif used and not share.tokens and facts.session_id in replied:
                share.why = _NO_TOKENS
                notes.append(
                    f"No tokens were recorded for {_label(facts)}, though the tutor replied in "
                    f"it, so its cost is not known. Part {part}'s cost is split over its other "
                    "lessons, so theirs may include some of it."
                )
            else:
                share.share = tokens[facts.session_id] / used if used else 1 / len(ran)
                share.cost = spent * share.share
            shares[facts.key] = share
    return shares, notes


def _placed(
    turns: list[Turn], requests: list[Sent]
) -> tuple[dict[str, Sent], dict[str | None, list[Sent]]]:
    """Where a pupil's requests in a lesson go in their conversation, in the order they were
    made: by turn, the request that wrote its line (the first to show that line, unless the
    teacher's guidance wrote it); and by turn, the requests that came after it and wrote no line
    of their own. A request answered with a line already shown goes after that line's turn; one
    refused or with no answer goes after the turn shown last before it, or under None when no
    line had been shown yet."""
    by_line = {t.agent_line_id: t for t in turns if t.agent_line_id}
    own: dict[str, Sent] = {}
    after: dict[str | None, list[Sent]] = {}
    shown: set[str] = set()
    last: str | None = None
    for request in requests:
        line = request.agent_line_id if request.status == 200 else None
        turn = by_line.get(line) if line else None
        if line is None or turn is None:
            after.setdefault(last, []).append(request)
            continue
        if line not in shown and not turn.request.get("guidance"):
            own[turn.id] = request
        else:
            after.setdefault(turn.id, []).append(request)
        shown.add(line)
        last = turn.id
    return own, after


# The moves whose words the writer is asked for, beyond the written moves: a double tap, whose
# one line is sent twice. A copied wrong answer is another pupil's words, not the writer's.
_DOUBLE_TAP = "double_tap"
_NOT_WRITTEN = frozenset({"copied_wrong"})
# Why the writer could not write a line, as it keeps the reason, in plain words. A reason not
# here is shown as the writer kept it.
_NO_REASON = "reason not recorded"
_WHY = {
    "unrealistic line": "the line did not read as a pupil's",
    "http 429": "too many requests (http 429)",
    "ReadTimeout": "no answer in time (ReadTimeout)",
    "ConnectTimeout": "no answer in time (ConnectTimeout)",
    "ConnectError": "could not reach the model (ConnectError)",
    "no message in the reply": "the reply had no message in it",
    "free practice run": "a free practice run, which writes none",
}


def _why(reason: object) -> str:
    if not isinstance(reason, str) or not reason.strip():
        return _NO_REASON
    return _WHY.get(reason, reason)


def _writer_lines(sent: list[Sent]) -> tuple[int, int]:
    """How many pupil lines the writer was asked for, and how many of them are stand-ins, from
    what the pupils sent. A double tap sends its one line twice, so its two requests count
    once."""
    written = stand_ins = taps = tapped_stand_ins = 0
    for s in sent:
        if s.beat == _DOUBLE_TAP:
            taps += 1
            tapped_stand_ins += s.fallback
        elif s.beat in BEATS and s.beat not in _NOT_WRITTEN:
            written += 1
            stand_ins += s.fallback
    return written + (taps + 1) // 2, stand_ins + (tapped_stand_ins + 1) // 2


def _notes(turn: Turn, request: Sent | None) -> list[str]:
    """What else the platform and the run kept about a turn, in plain words: what the pupil's
    message was meant as, how the tutor marked it and pitched the step, and where the platform
    stepped in."""
    notes = []
    if request is not None and sends_a_message(request.beat):
        if request.beat.startswith("button:"):
            notes.append("A help button, not typed words")
        else:
            notes.append(f"Meant as: {_move(request.beat)}")
        if request.fallback:
            notes.append("The pupil's words are a fixed line, as the writer gave nothing usable")
    mark = judgment(turn)
    if mark:
        notes.append(_MARKS.get(mark, f"The tutor's mark: {mark}"))
    if turn.call:
        notes.append(f"How it pitched the step: {_PITCHES.get(turn.call, turn.call)}")
    if turn.leak == "failed":
        notes.append("The platform's check found the answer in the tutor's draft")
    if "over_disclosure" in turn.conflicts:
        notes.append("The platform found more help than allowed in the tutor's draft")
    if turn.outcome == "regenerated":
        notes.append("The platform had the reply written again before it went out")
    elif turn.outcome == "withheld" and turn.agent_line_id is not None:
        notes.append(
            "The platform held the tutor's reply back, so the pupil saw this holding line instead"
        )
    return notes


# ---------- saying it plainly ----------


def _e(value: object) -> str:
    """Text from the run, made safe to put in the page."""
    return html.escape(str(value), quote=True)


def _words(text: str) -> str:
    """Someone's words as they wrote them, line breaks kept; "" for none."""
    return f'<span class="words">{_e(text)}</span>' if text else ""


def _count(n: int, one: str, many: str | None = None) -> str:
    """`n` and the word for that many: "1 pupil", "3 replies"."""
    return f"{n} {one if n == 1 else many or one + 's'}"


def _and(items: list[str]) -> str:
    """Items as a list in words: "Part 1 and Part 2"."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _add(codes: list[str], code: str) -> None:
    if code not in codes:
        codes.append(code)


def _behind(codes: list[str]) -> str:
    """The line marking a turn or a pupil behind failed checks."""
    return f"Behind failed check{'s' if len(codes) > 1 else ''}: {', '.join(codes)}"


def _day(value: object) -> str:
    """A date as the page says it, "22 November 2026"; text that is not a date as it is; ""
    for none."""
    said = "" if value is None else str(value)
    try:
        day = date.fromisoformat(said[:10])
    except ValueError:
        return said
    return f"{day.day} {day:%B %Y}"


def _amount(value: object) -> float | None:
    """A number of dollars, or None when it is not a number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _dollars(amount: float | None) -> str:
    if amount is None:
        return "not recorded"
    if 0 < amount < 0.005:
        return "under $0.01"
    return f"${amount:,.2f}"


def _names(value: object) -> list[str]:
    """Part names from meta: a list of names, or a dict of name to anything; none for
    anything else."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, dict | list | tuple):
        return [str(name) for name in value]
    return []


def _parts(value: object) -> str:
    """Parts of the day as the page says them: "Part 1 and Part 2", or "none". A dict of part
    to why says why: "Part 2 (not enough left on the key)"."""
    if isinstance(value, dict):
        said = [f"Part {name}" + (f" ({why})" if why else "") for name, why in value.items()]
    else:
        said = [f"Part {name}" for name in _names(value)]
    return _and(said) if said else "none"


def _listed(value: object) -> str:
    """Models or prompt versions as the page says them, from text, a list ("model-a,
    model-b"), or a dict of what to what ("tutor: model-a; pupils: model-b")."""
    if isinstance(value, dict):
        said = "; ".join(f"{k}: {v}" for k, v in value.items() if v not in (None, ""))
    elif isinstance(value, list | tuple):
        said = ", ".join(str(v) for v in value if v not in (None, ""))
    else:
        said = "" if value in (None, "") else str(value)
    return said or "not recorded"


def _label(facts: LessonFacts) -> str:
    """How the page names a lesson: "Part 2, Group A, lesson 2: English, 13 year olds"."""
    where = PLACES[facts.key][1] if facts.key in PLACES else f"Lesson {facts.key}"
    subject = facts.subject or "subject not known"
    age = f"{facts.age} year olds" if facts.age else "age not known"
    return f"{where}: {subject}, {age}"


def _drafted(drafted: Drafted | None) -> str:
    """How drafting a lesson went, from the teacher's record of it (None: not drafted)."""
    if drafted is None:
        return "Not drafted in this run"
    reason = drafted.reason.strip().rstrip(".")
    if drafted.lesson_id is None:
        return f"Not drafted: {reason}" if reason else "Not drafted"
    said = f"Drafted by the class agent after {_count(drafted.asked, 'message')} from the teacher"
    return f"{said}: {reason}" if reason else said


def _who(entry: dict | None) -> str:
    """Who a pupil is in the cast: "slow-1, an average pupil who gets there slowly"."""
    if not entry:
        return ""
    words = _KINDS.get(str(entry.get("kind")), "a pupil")
    steer = _STEERS.get(str(entry.get("steer")))
    if steer:
        words += f" {steer}"
    flags = [said for flag, said in _FLAGS.items() if entry.get(flag)]
    return ", ".join(filter(None, [str(entry.get("name") or ""), words, *flags]))


def _move(beat: str) -> str:
    """What a move was meant to be, in plain words."""
    return _MOVES.get(beat, beat.replace("_", " "))


def _refused(status: int) -> str:
    """Why a request got no answer, from its status."""
    if status in _REFUSED:
        return _REFUSED[status]
    if status >= 500:
        return f"the server failed (code {status})"
    return f"refused (code {status})"


def _detail(text: str) -> str:
    """A check's detail. Several lines of cells split by " | ", as T8 writes its table by
    subject, show as a table, and any lines after the table with no cells (a note under it) as a
    line each; any other detail as a line each."""
    lines = [line for line in str(text).split("\n") if line.strip()]
    cells = [line.split(" | ") for line in lines]
    rows = len(cells)
    while rows and len(cells[rows - 1]) == 1:
        rows -= 1
    table = cells[:rows]
    if rows > 1 and len({len(r) for r in table}) == 1 and len(table[0]) > 1:
        under = "".join(f'<p class="detail">{_e(line)}</p>' for line in lines[rows:])
        return _table(table[0], table[1:]) + under
    return "".join(f'<p class="detail">{_e(line)}</p>' for line in lines)


def _table(head: list[str], body: list[list[str]], numbers: Iterable[int] = ()) -> str:
    """A table of text, in a box of its own that scrolls sideways when the table is too wide
    for the screen. The columns in `numbers` are set to the right."""
    right = set(numbers)

    def cell(tag: str, column: int, value: str) -> str:
        style = ' class="num"' if column in right else ""
        return f"<{tag}{style}>{_e(value)}</{tag}>"

    header = "".join(cell("th", i, value) for i, value in enumerate(head))
    rows = "".join(
        "<tr>" + "".join(cell("td", i, value) for i, value in enumerate(row)) + "</tr>"
        for row in body
    )
    return (
        f'<div class="scroll"><table><thead><tr>{header}</tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


# ---------- the styles ----------

_LIGHT = """
  color-scheme: light;
  --bg: #ffffff; --text: #1d2125; --muted: #59626b; --line: #d8dce0; --link: #1d5ca6;
  --fail-bg: #fbe8e8; --fail: #8a1c1c; --notup-bg: #fcf1d6; --notup: #664800;
  --pass-bg: #e3f2e8; --pass: #1b5730; --info-bg: #eceef1; --info: #39424b;
"""
_DARK = """
  color-scheme: dark;
  --bg: #16191c; --text: #e4e7ea; --muted: #a2aab2; --line: #353b41; --link: #8bb8ee;
  --fail-bg: #3b1f1f; --fail: #f2b3b3; --notup-bg: #372d12; --notup: #eed18a;
  --pass-bg: #18321f; --pass: #a5d9b4; --info-bg: #262b30; --info: #ccd2d8;
"""
_RULES = """
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text); overflow-wrap: anywhere;
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 1.7rem; line-height: 1.2; margin: 0 0 6px; }
h2 {
  font-size: 1.3rem; line-height: 1.3; margin: 40px 0 8px; padding-top: 16px;
  border-top: 1px solid var(--line);
}
h3 { font-size: 1.05rem; line-height: 1.4; margin: 0; }
p { margin: 8px 0; }
a { color: var(--link); }
.muted { color: var(--muted); }
.banner {
  background: var(--info-bg); color: var(--info); border: 1px solid var(--line);
  border-radius: 8px; padding: 12px 14px; margin: 16px 0;
}
.counts {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 22px; margin: 20px 0 8px;
}
.counts strong { font-size: 1.7rem; margin-right: 2px; }
.counts .pass strong { color: var(--pass); }
.counts .fail strong { color: var(--fail); }
.counts .notup strong { color: var(--notup); }
.counts .info strong { color: var(--info); }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 16px 0; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; }
.toc { margin: 16px 0; color: var(--muted); }
.toc a { margin-left: 12px; white-space: nowrap; }
.check { border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; margin: 12px 0; }
.tag {
  display: inline-block; font-size: 0.8rem; font-weight: 600; line-height: 1.6;
  padding: 0 8px; border-radius: 999px; margin-right: 8px; vertical-align: 2px;
}
.tag.pass { background: var(--pass-bg); color: var(--pass); }
.tag.fail { background: var(--fail-bg); color: var(--fail); }
.tag.notup { background: var(--notup-bg); color: var(--notup); }
.tag.info { background: var(--info-bg); color: var(--info); }
.code { color: var(--muted); font-weight: 400; margin-right: 4px; }
.meaning { color: var(--muted); margin: 4px 0 0; }
.reach { font-weight: 600; }
summary { cursor: pointer; color: var(--link); margin: 8px 0 0; }
ol.evidence { list-style: none; padding: 0; margin: 4px 0 0; }
ol.evidence li { border-top: 1px solid var(--line); padding: 10px 0 2px; }
dl.item { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 0; }
dl.item dt { color: var(--muted); }
dl.item dd { margin: 0; }
.words { white-space: pre-wrap; }
.scroll { overflow-x: auto; margin: 8px 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.95rem; overflow-wrap: normal; }
th, td {
  text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); vertical-align: top;
}
th { font-weight: 600; }
th:first-child, td:first-child { min-width: 8em; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
td.num { white-space: nowrap; }
.lesson { margin: 28px 0; }
details.pupil {
  border: 1px solid var(--line); border-radius: 8px; margin: 8px 0; padding: 4px 12px 8px;
}
details.pupil > summary { color: var(--text); }
.turn { border-top: 1px solid var(--line); padding: 8px 0; }
.turn p { margin: 4px 0; }
.who { font-weight: 600; margin-right: 8px; }
.note { color: var(--muted); font-size: 0.9rem; }
.flag { color: var(--fail); font-weight: 600; font-size: 0.9rem; }
ul.actions { margin: 4px 0; padding-left: 20px; color: var(--muted); font-size: 0.9rem; }
ul.plain { margin: 4px 0; padding-left: 20px; }
@media (max-width: 520px) {
  .facts, dl.item { grid-template-columns: 1fr; gap: 0; }
  .facts dd, dl.item dd { margin-bottom: 8px; }
  th, td { padding: 6px; }
}
"""
_STYLE = (
    ":root {" + _LIGHT + "}\n"
    '@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {' + _DARK + "} }\n"
    ':root[data-theme="dark"] {' + _DARK + "}\n" + _RULES
)
