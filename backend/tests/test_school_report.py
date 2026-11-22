"""The report of a school day run (bench/school/report.py): one page the platform's owner reads,
and may show to a professor, beside a JSON file of everything behind it. Each test builds a small
run by hand: no database, no platform and no model."""

import itertools
import json
import re
from datetime import UTC, date, datetime, timedelta
from html import escape, unescape

import pytest

from app.agent.student_mode import HELD_BACK
from bench.school import report
from bench.school.checks import Evidence, Result
from bench.school.collect import LessonFacts, RunData, Turn
from bench.school.driver import Sent
from bench.school.report import render, save
from bench.school.teacher import Drafted

START = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)
SCRIPT = "<script>alert(1)</script>"
# Words that would close an attribute and open a tag of their own if not escaped.
ATTRIBUTE = '"><img src=x onerror=alert(1)>'
# The long dashes the report never uses, written as code points.
EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)
# The checks on the platform's own workings, which count even in a free run (the controller's
# list), and checks whose result depends on what a model wrote, which do not.
MACHINERY = (
    *("S1", "S2", "S3", "S5", "U1", "U2", "U3", "U4", "U5", "U6", "U7", "C6", "C7", "C8"),
    *("C9", "C12", "C14", "X1", "X2", "X3", "R1", "M4", "M5"),
)
MODEL_WRITTEN = (
    *("T1", "T9", "T12", "P1", "P8", "M1", "M2", "M3", "C1", "C4", "C5", "C10", "C11"),
    *("C13", "S4"),
)
_numbers = itertools.count(1)


def _next() -> int:
    return next(_numbers)


def turn(
    pupil: str,
    session: str = "S1",
    *,
    said: str = "",
    reply: str = "A reply from the tutor.",
    line: str | None = None,
    usage: dict | None = None,
    assessment: str | None = None,
    call: str | None = None,
    outcome: str = "ok",
    leak: str = "passed",
    conflicts: tuple[str, ...] = (),
    request: dict | None = None,
    wrote: bool = True,
) -> Turn:
    """A tutor's turn as collect gives one: by default a reply that went out, with no tokens
    recorded. With `wrote` false the model gave no answer, so the turn wrote no line."""
    n = _next()
    return Turn(
        id=f"turn-{n}",
        session_id=session,
        pupil=pupil,
        model="openai/gpt-5.4",
        prompt_version="p-7",
        manifest={},
        reply={"assessment": {"judgment": assessment}} if assessment else {},
        conflicts=list(conflicts),
        outcome=outcome,
        leak=leak,
        latency_ms=900,
        said=said,
        reply_text=reply if wrote else "",
        agent_line_id=(line or f"line-{n}") if wrote else None,
        at=(START + timedelta(seconds=n)).isoformat(),
        request=request if request is not None else {"text": said or None},
        usage=dict(usage or {}),
        call=call,
    )


def sent(
    pupil: str,
    beat: str,
    text: str = "",
    *,
    session: str = "S1",
    line: str | None = None,
    status: int = 200,
    fallback: bool = False,
) -> Sent:
    """A request a pupil made, as the driver logs it."""
    return Sent(
        pupil=pupil,
        kind="average",
        session_id=session,
        beat=beat,
        text=text,
        status=status,
        seconds=2.0,
        agent_line_id=line,
        at=(START + timedelta(seconds=_next())).isoformat(),
        fallback=fallback,
        step_index=0,
        wrong_tries=0,
        lines=2,
    )


def lesson(
    key: str = "full-class",
    session: str = "S1",
    *,
    subject: str = "maths",
    age: int | None = 14,
    drafted: Drafted | None = None,
) -> LessonFacts:
    return LessonFacts(
        key=key,
        session_id=session,
        subject=subject,
        age=age,
        steps=4,
        rules={},
        brief={"subject": subject},
        teacher="sd-maths-11220900",
        drafted=drafted,
    )


def who(name: str, kind: str = "average", steer: str | None = None, **flags) -> dict:
    """A pupil of the cast, as the driver describes one."""
    return {
        "name": name,
        "kind": kind,
        "steer": steer,
        "eal": False,
        "note_target": False,
        "guide_target": False,
        "joins_after_s": 0,
        "signs_back_in": False,
        **flags,
    }


def run(*, lessons=None, turns=(), sent=(), cast=None, errors=(), events=()) -> RunData:
    """A run with these records and nothing else; Part 1's lesson as S1 unless given."""
    return RunData(
        lessons=list(lessons) if lessons is not None else [lesson()],
        turns=list(turns),
        sent=list(sent),
        events=list(events),
        alerts=[],
        access=[],
        outcomes=[],
        notes=[],
        note_lines={},
        evidence_subject={},
        guidance=[],
        states=[],
        teacher_replies=[],
        view_seconds=[],
        errors=list(errors),
        cast=dict(cast or {}),
    )


def result(code: str, outcome: str, *, detail: str = "", evidence=()) -> Result:
    return Result(
        code,
        f"Title of {code}",
        f"What {code} means.",
        outcome,
        detail or f"Detail of {code}.",
        list(evidence),
    )


def meta(**changes) -> dict:
    """A paid run of both parts, unless changed."""
    return {
        "date": "2026-11-22",
        "parts_run": ["1", "2"],
        "parts_not_run": [],
        "models": {
            "tutor and class agent": "openai/gpt-5.4",
            "pupils": "anthropic/claude-sonnet-5.5",
        },
        "prompt_versions": {"tutor": "p-7"},
        "cost": 15.0,
        "free": False,
        "cost_by_part": {"1": 6.0, "2": 9.0},
        **changes,
    }


def text(page: str) -> str:
    """A page as a reader sees it: no styles or tags, entities read, spaces tidied."""
    shown = re.sub(r"<style.*?</style>", " ", page, flags=re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", shown)).split())


def section(page: str, name: str) -> str:
    """One of the page's sections, by its id, as a reader sees it."""
    found = re.search(rf'<section id="{name}".*?</section>', page, flags=re.S)
    assert found, f"the page has no section {name}"
    return text(found.group(0))


def rows(page: str, name: str) -> list[str]:
    """Every table row in one of the page's sections, as a reader sees it."""
    found = re.search(rf'<section id="{name}".*?</section>', page, flags=re.S)
    assert found, f"the page has no section {name}"
    return [text(row) for row in re.findall(r"<tr>.*?</tr>", found.group(0), flags=re.S)]


def has(shown: str, code: str) -> bool:
    """Whether the check with this code is in the text, by its whole code: C1 is not C12."""
    return re.search(rf"Title of {code}\b", shown) is not None


def row(page: str, name: str, words: str) -> str:
    """The one table row in a section that has these words."""
    found = [r for r in rows(page, name) if words in r]
    assert len(found) == 1, (words, found)
    return found[0]


def every_kind_of_result() -> list[Result]:
    """One result of every outcome, with evidence of every shape and a detail that is a
    table, as T8 writes one."""
    table = (
        "Subject | T1 | T2 | T3 | T4 | T5\n"
        "maths | pass | pass (9 of 10) | pass | pass | pass\n"
        "English | fail | did not come up | pass | pass | pass"
    )
    evidence = [
        Evidence(
            "QX7RT",
            "full-class",
            "x = 6",
            "Yes, x = 6 is right!",
            "The tutor marked this wrong answer as right.",
        ),
        Evidence("ZZ9AB", "a-maths", "", "", "The tutor never asked them a harder version."),
        Evidence("", "", "", "", "Nothing reached the teacher."),
        Evidence("QX7RT", "a lesson the run does not know", "hi", "", "A note."),
    ]
    return [
        result("T1", "fail", evidence=evidence[:1]),
        result("T8", "fail", detail=table, evidence=evidence),
        result("C5", "fail", detail="A first line.\nA second line."),
        result("P2", "did not come up"),
        result("M2", "did not come up"),
        result("S5", "did not come up"),
        result("Z9", "did not come up"),
        result("T3", "pass"),
        result("C4", "pass"),
    ]


def full_run() -> RunData:
    """A run with something of everything the page shows: lessons drafted, not drafted and
    never run, both parts, a part with tokens and one without, every kind of note on a turn,
    requests refused in every way, the whole cast and an error."""
    lessons = [
        lesson("full-class", "S1", drafted=Drafted("lesson-1", 2, "written as a change to X.")),
        lesson("a-maths", "S2", age=13, drafted=Drafted("lesson-2", 1)),
        lesson(
            "a-english",
            "",
            subject="English",
            age=13,
            drafted=Drafted(None, 3, "the class agent kept asking questions"),
        ),
        lesson("b-history", "S4", subject="history", age=16),
        lesson("b-science", "S5", subject="science", age=16, drafted=Drafted(None, 1)),
    ]
    turns = [
        turn(
            "QX7RT",
            "S1",
            reply="Welcome. Solve 2x + 3 = 11.",
            line="L1",
            usage={"total_tokens": 400},
        ),
        turn(
            "QX7RT",
            "S1",
            said="x = 6",
            reply="Yes, x = 6 is right!",
            line="L2",
            usage={"total_tokens": 600},
            assessment="met",
            call="stretched",
            outcome="regenerated",
            leak="failed",
            conflicts=("over_disclosure",),
        ),
        turn(
            "QX7RT",
            "S1",
            said="idk",
            reply="Let's keep this one yours.",
            line="L3",
            outcome="withheld",
        ),
        turn("QX7RT", "S1", said="what", wrote=False, outcome="withheld"),
        turn(
            "QX7RT",
            "S1",
            line="L4",
            reply="Here is a hint about the first step.",
            request={"text": None, "guidance": "Give them a hint about the first step."},
        ),
        turn(
            "ZZ9AB",
            "S2",
            said="15% is 9",
            reply="Good.",
            usage={"total_tokens": 1000},
            call="let go",
        ),
        turn(
            "ZZ9AB",
            "S2",
            said="Why is my answer wrong?",
            reply="Look at the sign.",
            assessment="partial",
        ),
        turn("HB4KD", "S4", said="the alliances", reply="Which one first?", assessment="not_met"),
        turn(
            "HB4KD",
            "S5",
            said="glucose",
            reply="And what else?",
            assessment="unclear",
            call="stayed",
        ),
    ]
    requests = [
        sent("QX7RT", "open", session="S1", line="L1"),
        sent("QX7RT", "confident_wrong", "x = 6", session="S1", line="L2", fallback=True),
        sent("QX7RT", "ask_teacher", session="S1", line="L2"),
        sent("QX7RT", "helped", session="S1", line="L2"),
        sent("QX7RT", "no_movement", "idk", session="S1", line="L3"),
        sent("QX7RT", "what_mean", "what", session="S1", status=503),
        sent("QX7RT", "leave", session="S1", line="L3"),
        sent("QX7RT", "come_back", session="S1", line="L3"),
        sent("QX7RT", "signed_back_in", session="S1", line="L4"),
        sent("QX7RT", "right", "x = 4", session="S1", status=409),
        sent("QX7RT", "double_tap", "x = 5", session="S1", status=429),
        sent("QX7RT", "right", "x = 4", session="S1", status=0),
        sent("QX7RT", "right", "x = 4", session="S1", status=500),
        sent("QX7RT", "made_up_move", "x", session="S1", status=418),
        sent("ZZ9AB", "button:why_wrong", session="S2"),
        sent("HB4KD", "jump", session="S5"),
    ]
    cast = {
        "QX7RT": who("strong-1", "strong", steer="strong", joins_after_s=180, signs_back_in=True),
        "ZZ9AB": who(
            "a-slow", "average", steer="slow", eal=True, note_target=True, guide_target=True
        ),
        "HB4KD": who("b-recovers", "average", steer="recovers"),
        "NOBODY": who("trick", "trick"),
    }
    return run(
        lessons=lessons,
        turns=turns,
        sent=requests,
        cast=cast,
        errors=["QX7RT, what_mean: no reply came"],
    )


# ---------- the order of the page ----------


def test_the_report_counts_and_lists_failures_first():
    evidence = Evidence(
        "QX7RT",
        "full-class",
        "x = 6",
        "Yes, x = 6 is right!",
        "The tutor marked this wrong answer as right.",
    )
    results = [
        result("T2", "pass"),
        result("T1", "fail", evidence=[evidence]),
        result("P2", "did not come up"),
        result("T3", "pass"),
    ]
    page = render(results, run(), meta())
    shown = text(page)

    assert "2 passed" in shown and "1 failed" in shown and "1 did not come up" in shown
    # The counts come first, then the failures, then what did not come up, then the passes.
    assert shown.index("1 failed") < shown.index("Title of T1")
    assert (
        shown.index("Title of T1")
        < shown.index("Title of P2")
        < shown.index("Title of T2")
        < shown.index("Title of T3")
    )
    # Every check shows the line saying what it means under its title.
    for each in results:
        assert shown.index(each.title) < shown.index(each.meaning)
        assert shown.index(each.meaning) - shown.index(each.title) < 60
    # The failure opens to its evidence: the pupil, the lesson, what they said, the tutor's
    # reply and the note, the lesson named as a reader knows it.
    failed = section(page, "failed")
    for part in (
        "QX7RT",
        "Part 1: maths, 14 year olds",
        "x = 6",
        "Yes, x = 6 is right!",
        "The tutor marked this wrong answer as right.",
        "Detail of T1.",
    ):
        assert part in failed, part
    assert re.search(r"<details>\s*<summary>[^<]*1\)</summary>", page)
    # Each outcome says what it is in words, not by colour alone.
    assert "Failed" in failed
    assert "Did not come up" in section(page, "not-up")
    assert "Passed" in section(page, "passed")


def test_the_top_says_the_cost_the_models_the_prompts_and_the_parts_that_did_not_run():
    page = render(
        [result("T1", "fail")],
        run(),
        meta(parts_run=["1"], parts_not_run=["2"], cost=6.25, cost_by_part={"1": 6.25}),
    )
    shown = text(page)
    top = shown[: shown.index("Title of T1")]

    assert "22 November 2026" in top
    assert "$6.25" in top
    assert "openai/gpt-5.4" in top and "anthropic/claude-sonnet-5.5" in top and "p-7" in top
    assert "Parts run Part 1" in top
    assert "Parts that did not run Part 2" in top
    assert "Parts that did not run none" in text(render([], run(), meta()))

    # The runner may say why a part did not run, and give the models as a list.
    shown = text(
        render(
            [],
            run(),
            meta(
                parts_run="1",
                parts_not_run={"2": "not enough left on the key"},
                models=["openai/gpt-5.4", "anthropic/claude-sonnet-5.5"],
            ),
        )
    )
    assert "Parts run Part 1" in shown
    assert "Parts that did not run Part 2 (not enough left on the key)" in shown
    assert "Models openai/gpt-5.4, anthropic/claude-sonnet-5.5" in shown


def fell_back(pupil: str, beat: str, why: str | None) -> dict:
    """The driver's note of a line the writer could not write."""
    return {"what": "writer fell back", "pupil": pupil, "beat": beat, "why": why, "at": "x"}


def test_the_top_says_how_many_pupil_lines_were_stand_ins_and_why():
    written = [sent("QX7RT", "right", "x = 5", line=f"L{n}") for n in range(6)]
    stand_ins = [
        sent("QX7RT", "right", "i did it step by step", line="M1", fallback=True),
        sent("QX7RT", "wrong", "is it 10", line="M2", fallback=True),
        sent("ZZ9AB", "right_why", "i did it step by step", line="M3", fallback=True),
        sent("ZZ9AB", "how", "i did it step by step", line="M4", fallback=True),
    ]
    # A double tap's one line is sent twice, and counts once; the opening, a fixed text and a
    # copied answer are not the writer's lines, so they are not counted.
    others = [
        sent("ZZ9AB", "double_tap", "is it 10", line="M5", fallback=True),
        sent("ZZ9AB", "double_tap", "is it 10", status=429, fallback=True),
        sent("ZZ9AB", "open", line="M0"),
        sent("ZZ9AB", "greek", "δεν καταλαβαίνω", line="M6"),
        sent("ZZ9AB", "copied_wrong", "is it 10", line="M7"),
    ]
    events = [
        fell_back("QX7RT", "right", "unrealistic line"),
        fell_back("QX7RT", "wrong", "http 429"),
        fell_back("ZZ9AB", "right_why", "unrealistic line"),
        fell_back("ZZ9AB", "how", "ReadTimeout"),
        fell_back("ZZ9AB", "wrong", "unrealistic line"),
        {"what": "rate limited", "pupil": "ZZ9AB", "beat": "right", "at": "y"},
    ]
    page = render(
        [result("T1", "fail")], run(sent=written + stand_ins + others, events=events), meta()
    )
    shown = text(page)
    top = shown[: shown.index("Title of T1")]
    assert (
        "Pupil lines the writer could not write, so a stand-in line was sent: 5 of 11 "
        "(the line did not read as a pupil's: 3; too many requests (http 429): 1; "
        "no answer in time (ReadTimeout): 1)"
    ) in top
    assert EM_DASH not in top and EN_DASH not in top


def test_stand_in_lines_with_no_reason_kept_say_so():
    # A run logged before the driver kept the reason: the stand-ins are still counted.
    lines = [
        sent("QX7RT", "right", "x = 5", line="L1"),
        sent("QX7RT", "right", "i did it step by step", line="L2", fallback=True),
        sent("QX7RT", "wrong", "is it 10", line="L3", fallback=True),
    ]
    shown = text(render([], run(sent=lines, events=[fell_back("QX7RT", "right", None)]), meta()))
    assert (
        "Pupil lines the writer could not write, so a stand-in line was sent: 2 of 3 "
        "(reason not recorded: 2)"
    ) in shown
    # An unknown reason is shown as the writer kept it; none at all says so.
    events = [fell_back("QX7RT", "right", "no message in the reply"), fell_back("Q", "w", "odd")]
    shown = text(render([], run(sent=lines, events=events), meta()))
    assert "2 of 3 (the reply had no message in it: 1; odd: 1)" in shown
    shown = text(render([], run(sent=lines[:1]), meta()))
    assert "Pupil lines the writer could not write, so a stand-in line was sent: none of 1" in (
        shown
    )
    shown = text(render([], run(), meta()))
    assert "Pupil lines the writer could not write" not in shown


def test_did_not_come_up_is_listed_on_its_own_and_never_as_passed():
    results = [result("M2", "did not come up"), result("T3", "pass")]
    page = render(results, run(), meta(parts_run=["1"], parts_not_run=["2"]))
    shown = text(page)

    assert "1 passed" in shown and "0 failed" in shown and "1 did not come up" in shown
    not_up = section(page, "not-up")
    assert "Title of M2" in not_up and "What M2 means." in not_up
    # It says which part reaches it, and that the part did not run this time.
    assert "Part 2, Group A" in not_up
    assert "Part 2 did not run this time." in not_up
    assert "Title of M2" not in section(page, "passed")
    assert "Title of T3" not in not_up

    # A run in which nothing came up passes nothing.
    page = render([result("P1", "did not come up")], run(), meta())
    assert "0 passed" in text(page) and "1 did not come up" in text(page)
    assert "Title of P1" in section(page, "not-up")
    assert "Title of P1" not in section(page, "passed")
    assert "To reach it, run either part." in section(page, "not-up")
    assert "did not run this time" not in section(page, "not-up")


def test_a_free_run_says_so_at_the_top_and_counts_only_the_checks_that_mean_something():
    results = [
        result("T1", "fail"),
        result("P1", "pass"),
        result("T6", "did not come up"),
        result("C5", "fail"),
        result("S1", "pass"),
        result("C6", "fail"),
    ]
    page = render(results, run(), meta(free=True, cost=0.0, cost_by_part={}))
    shown = text(page)

    assert "free practice run" in shown and "scripted stand-in" in shown
    top = shown[: shown.index("1 passed")]
    assert "free practice run" in top and "depends on what a model wrote" in top
    assert "1 passed" in shown and "1 failed" in shown and "0 did not come up" in shown
    assert "4 informational" in shown
    informational = section(page, "informational")
    for code in ("T1", "P1", "T6", "C5"):
        assert f"Title of {code}" in informational
        assert f"What {code} means." in informational
    assert "Informational: failed" in informational
    assert "Title of T1" not in section(page, "failed")
    assert "Title of P1" not in section(page, "passed")
    assert "Title of C5" not in section(page, "failed")
    assert "Title of C6" in section(page, "failed")
    assert "Title of S1" in section(page, "passed")
    assert "nothing was spent" in section(page, "cost")

    paid = render(results, run(), meta())
    assert "free practice run" not in text(paid)
    assert 'id="informational"' not in paid
    assert "Title of T1" in section(paid, "failed")


def test_in_a_free_run_only_the_checks_on_the_platforms_own_workings_count():
    results = [result(code, "fail") for code in (*MACHINERY, *MODEL_WRITTEN)]
    page = render(results, run(), meta(free=True))
    failed, informational = section(page, "failed"), section(page, "informational")

    # Codes are matched whole: C1 is informational though C12 and C14 count.
    for code in MACHINERY:
        assert has(failed, code) and not has(informational, code), code
    for code in MODEL_WRITTEN:
        assert has(informational, code) and not has(failed, code), code
    shown = text(page)
    assert f"{len(MACHINERY)} failed" in shown
    assert f"{len(MODEL_WRITTEN)} informational" in shown


# ---------- the cost ----------


def test_the_cost_per_pupil_per_lesson_is_shown():
    lessons = [
        lesson("full-class", "S1"),
        lesson("a-maths", "S2", age=13),
        lesson("b-history", "S3", subject="history", age=16),
    ]
    turns = [
        # Part 1: four pupils, 2,000 tokens.
        *[turn(p, "S1", usage={"total_tokens": 500}) for p in ("P1", "P2", "P3", "P4")],
        # Part 2: Group A's maths has three pupils and 3,000 tokens; Group B's history has two
        # pupils and 1,000 tokens, one turn with no usage counted as none.
        *[turn(p, "S2", usage={"total_tokens": 1000}) for p in ("A1", "A2", "A3")],
        turn("B1", "S3", usage={"total_tokens": 1000}),
        turn("B2", "S3"),
    ]
    page = render(
        [], run(lessons=lessons, turns=turns), meta(cost=14.5, cost_by_part={"1": 6.0, "2": 8.0})
    )

    assert "$6.00" in row(page, "cost", "Part 1 $")
    assert "$8.00" in row(page, "cost", "Part 2 $")
    assert "$14.50" in row(page, "cost", "In all")
    full_class = row(page, "cost", "Part 1: maths, 14 year olds")
    assert "2,000" in full_class and "$6.00" in full_class and " 4 " in full_class
    assert "$1.50" in full_class
    group_a = row(page, "cost", "Part 2, Group A, lesson 1: maths, 13 year olds")
    assert "75%" in group_a and "$6.00" in group_a and " 3 " in group_a and "$2.00" in group_a
    group_b = row(page, "cost", "Part 2, Group B, lesson 1: history, 16 year olds")
    assert "25%" in group_b and "$2.00" in group_b and " 2 " in group_b and "$1.00" in group_b
    # The money comes before the tokens, so a phone shows it without scrolling.
    header = row(page, "cost", "Cost per pupil")
    assert header.index("Cost per pupil") < header.index("Tutor tokens")
    # The lesson's own section says it too.
    assert "Cost: $6.00 for the lesson, $1.50 a pupil." in section(page, "lessons")


def test_a_part_with_no_tokens_is_split_evenly_and_the_page_says_so():
    lessons = [
        lesson("a-maths", "S2", age=13),
        lesson("a-english", "S3", subject="English", age=13),
        lesson("a-maths-2", "", age=13),
    ]
    turns = [turn("A1", "S2"), turn("A2", "S2"), turn("A1", "S3")]
    page = render(
        [],
        run(lessons=lessons, turns=turns),
        meta(parts_run=["2"], cost=4.0, cost_by_part={"2": 4.0}),
    )

    maths = row(page, "cost", "Group A, lesson 1")
    english = row(page, "cost", "Group A, lesson 2")
    assert "$2.00" in maths and "$1.00" in maths
    assert "$2.00" in english and "$2.00" in english.split("$2.00", 1)[1]
    assert "did not run" in row(page, "cost", "Group A, lesson 3")
    # The part's row counts only the two lessons that ran.
    assert row(page, "cost", "Part 2 $") == "Part 2 $4.00 2 0"
    assert "No tokens were recorded for Part 2, so its cost is split evenly" in section(
        page, "cost"
    )


def test_a_cost_that_was_not_recorded_is_never_made_up():
    page = render([], run(turns=[turn("P1", "S1")]), meta(cost=None, cost_by_part={}))
    cost = section(page, "cost")
    assert "not recorded" in row(page, "cost", "Part 1: maths, 14 year olds")
    assert "$" not in cost.split("Per lesson", 1)[1]
    assert "Cost not recorded Models" in text(page)

    # A part that spent money but none of whose lessons ran gives none of it to a lesson.
    lessons = [lesson("full-class", "S1"), lesson("c-english", "", subject="English", age=12)]
    page = render(
        [],
        run(lessons=lessons, turns=[turn("P1", "S1"), turn("P2", "S1"), turn("P3", "S1")]),
        meta(cost=0.41, cost_by_part={"1": 0.01, "2": 0.4}),
    )
    assert "None of Part 2's lessons ran, so its cost of $0.40 is not split." in section(
        page, "cost"
    )
    assert "$" not in row(page, "cost", "Group C, lesson 1")
    # A cost too small to show in cents says so, rather than reading as nothing.
    assert "under $0.01" in row(page, "cost", "Part 1: maths, 14 year olds")


def test_a_part_that_ran_with_no_recorded_cost_is_never_left_out_of_the_whole():
    # Whatever total the runner gives, the parts recorded are not the whole when one is missing.
    for given in (None, 0.4):
        page = render([], run(), meta(cost=given, cost_by_part={"1": None, "2": 0.4}))
        shown = text(page)
        assert "Cost at least $0.40 (Part 1 not recorded)" in shown
        assert "$0.40 in all" not in shown
        assert row(page, "cost", "In all") == "In all at least $0.40 (Part 1 not recorded) 1 0"


def test_a_cost_that_cannot_be_split_says_why():
    # Part 2 spent money, but no lesson of it is listed.
    page = render(
        [],
        run(turns=[turn("P1", "S1", usage={"total_tokens": 10})]),
        meta(cost=2.4, cost_by_part={"1": 2.0, "2": 0.4}),
    )
    assert (
        "Part 2 cost $0.40, but no lesson of it is listed, so its cost could not be split."
        in section(page, "cost")
    )

    # The tutor replied in Group A's English but no tokens were recorded there, while its maths
    # recorded them: its cost is not known, never $0.00 as if it were free.
    lessons = [
        lesson("a-maths", "S2", age=13),
        lesson("a-english", "S3", subject="English", age=13),
    ]
    turns = [turn("A1", "S2", usage={"total_tokens": 1000}), turn("A1", "S3")]
    page = render(
        [],
        run(lessons=lessons, turns=turns),
        meta(parts_run=["2"], cost=3.0, cost_by_part={"2": 3.0}),
    )
    english = row(page, "cost", "Group A, lesson 2")
    assert "$" not in english and "tokens not recorded" in english
    assert "$3.00" in row(page, "cost", "Group A, lesson 1")
    assert (
        "No tokens were recorded for Part 2, Group A, lesson 2: English, 13 year olds, though "
        "the tutor replied in it, so its cost is not known." in section(page, "cost")
    )
    assert "Cost: not known, as the tutor's tokens were not recorded in this lesson." in section(
        page, "lessons"
    )


# ---------- the lessons and pupils ----------


def test_every_lesson_shows_each_pupils_whole_conversation():
    lessons = [
        lesson("full-class", "S1"),
        lesson("a-maths", "S2", age=13),
        lesson("b-science", "", subject="science", age=16),
    ]
    turns = [
        turn("QX7RT", "S1", reply="Welcome. Solve 2x + 3 = 11.", line="L1"),
        turn(
            "QX7RT",
            "S1",
            said="x = 4",
            reply="Yes, well done.",
            line="L2",
            assessment="met",
            call="stretched",
        ),
        turn("ZZ9AB", "S2", said="15% is 9", reply="Good. Now try 35% of 80.", line="L3"),
        turn("ZZ9AB", "S2", said="Can you give me an example?", reply="Say 10% of 50.", line="L4"),
    ]
    requests = [
        sent("QX7RT", "open", session="S1", line="L1"),
        sent("QX7RT", "right", "x = 4", session="S1", line="L2"),
        sent("QX7RT", "ask_teacher", session="S1", line="L2"),
        sent("QX7RT", "right", "x = 5", session="S1", status=409),
        sent("ZZ9AB", "button:example", session="S2", line="L4"),
    ]
    cast = {
        "QX7RT": who("strong-1", "strong", steer="strong"),
        "ZZ9AB": who("a-slow", "average", steer="slow", eal=True),
    }
    page = render([], run(lessons=lessons, turns=turns, sent=requests, cast=cast), meta())
    shown = section(page, "lessons")

    first = shown[shown.index("Part 1: maths, 14 year olds") : shown.index("Group A, lesson 1")]
    for words in (
        "QX7RT",
        "strong-1, a strong pupil",
        "opened the lesson",
        "Welcome. Solve 2x + 3 = 11.",
        "x = 4",
        "Yes, well done.",
        "Meant as: a right answer",
        "The tutor marked it right",
        "asked a harder version",
        "Pressed Ask my teacher",
        "refused: the lesson was paused, closed or out of time",
    ):
        assert words in first, words
    assert (
        first.index("Welcome.")
        < first.index("x = 4")
        < first.index("Yes, well done.")
        < first.index("Pressed Ask my teacher")
        < first.index("x = 5")
    )
    assert "ZZ9AB" not in first
    # The lesson lists its pupils, each a link to their conversation.
    assert "Pupils: QX7RT" in first
    assert '<a href="#lesson-1-pupil-1">QX7RT</a>' in page
    group_a = shown[shown.index("Group A, lesson 1") :]
    assert "ZZ9AB" in group_a and "who gets there slowly, learning English" in group_a
    assert "Good. Now try 35% of 80." in group_a
    # A help button shows the words the pupil's page shows, and says it was a button.
    assert "Can you give me an example? Tutor Say 10% of 50." in group_a
    assert "A help button, not typed words" in group_a
    assert "This lesson did not run." in shown[shown.index("Group B, lesson 2") :]


def test_a_turn_behind_a_failed_check_is_marked_in_the_conversation():
    turns = [turn("QX7RT", "S1", said="x = 6", reply="Yes, x = 6 is right!")]
    evidence = Evidence("QX7RT", "full-class", "x = 6", "Yes, x = 6 is right!", "Marked right.")
    page = render([result("T1", "fail", evidence=[evidence])], run(turns=turns), meta())
    shown = section(page, "lessons")
    assert "Failed checks with evidence in this lesson: T1 (1)." in shown
    assert "Behind failed check: T1" in shown

    # In a free run, a teaching check is informational, so nothing is marked as failed.
    free = render([result("T1", "fail", evidence=[evidence])], run(turns=turns), meta(free=True))
    assert "Behind failed check" not in section(free, "lessons")


def test_only_the_turn_behind_a_failed_check_is_marked_when_replies_repeat():
    # A reply held back shows the platform's fixed holding line, so two held-back turns read the
    # same: what the pupil said tells them apart.
    turns = [
        turn("QX7RT", said="idk", reply=HELD_BACK, outcome="withheld"),
        turn("QX7RT", said="dunno", reply=HELD_BACK, outcome="withheld"),
    ]
    evidence = Evidence("QX7RT", "full-class", "idk", HELD_BACK, "Not let go in time.")
    page = render([result("P3", "fail", evidence=[evidence])], run(turns=turns), meta())
    found = re.search(r'<section id="lessons".*?</section>', page, flags=re.S)
    assert found
    lessons = found.group(0)
    marker = '<p class="flag">Behind failed check'
    assert lessons.count(marker) == 1
    assert lessons.index(">idk<") < lessons.index(marker) < lessons.index(">dunno<")


def test_a_refused_request_says_which_refusal_it_was():
    requests = [
        sent("QX7RT", "open", line="L1"),
        paused := sent("QX7RT", "right", "x = 4", status=409),
        time_up := sent("QX7RT", "wrong", "x = 9", status=409),
        closed := sent("QX7RT", "not_sure", "um", status=409),
        unknown := sent("QX7RT", "how", "i took 3", status=409),
    ]

    def refusal(what: str, request: Sent, pupil: str = "QX7RT") -> dict:
        return {"what": what, "pupil": pupil, "beat": request.beat, "at": request.at, "detail": ""}

    events = [
        refusal("paused", paused),
        refusal("time up", time_up),
        refusal("closed", closed),
        # Another pupil's refusal says nothing about this pupil's request.
        refusal("closed", unknown, pupil="ZZ9AB"),
        {"what": "pupils stopped", "at": unknown.at},
        {"probe": "x1", "path": "/api/learn/S9", "status": 404},
    ]
    turns = [turn("QX7RT", reply="Welcome.", line="L1")]
    page = render([], run(turns=turns, sent=requests, events=events), meta())
    shown = section(page, "lessons")

    assert '"x = 4", meant as: a right answer (refused: the lesson was paused)' in shown
    assert "a wrong answer from a slip (refused: the lesson's time was up)" in shown
    assert '"um", meant as: not sure (refused: the lesson was closed)' in shown
    assert "how they worked it out (refused: the lesson was paused, closed or out of time)" in shown


def test_the_whole_conversation_link_lands_on_an_open_conversation():
    evidence = Evidence("QX7RT", "full-class", "x = 6", "Yes!", "Marked right.")
    turns = [turn("QX7RT", said="x = 6", reply="Yes!")]
    page = render([result("T1", "fail", evidence=[evidence])], run(turns=turns), meta())

    targets = re.findall(r'<a href="#([^"]+)">the whole conversation</a>', page)
    assert targets
    for target in targets:
        assert f'<details class="pupil" id="{target}" open>' in page


# ---------- what the page is made of ----------


def hostile(words: str) -> tuple[list[Result], RunData, dict]:
    """A run with these words in every field the page shows."""
    evidence = Evidence(words, words, words, words, words)
    results = [
        Result(words, words, words, "fail", words, [evidence]),
        Result("T3", words, words, "did not come up", f"{words} | x\n{words} | y", []),
    ]
    facts = LessonFacts(
        key=words,
        session_id="S1",
        subject=words,
        age=14,
        steps=3,
        rules={},
        brief={},
        teacher=words,
        drafted=Drafted("lesson-1", 1, words),
    )
    turns = [
        turn(words, said=words, reply=words, call=words, assessment=words),
        turn(words, reply=words, request={"text": None, "guidance": words}),
    ]
    refused = sent(words, words, words, status=409)
    requests = [refused, sent(words, "ask_teacher", words)]
    events = [{"what": "paused", "pupil": words, "beat": words, "at": refused.at, "detail": words}]
    cast = {words: who(words, words, steer=words)}
    data = run(
        lessons=[facts], turns=turns, sent=requests, cast=cast, errors=[words], events=events
    )
    return (
        results,
        data,
        meta(
            date=words,
            models=words,
            prompt_versions={words: words},
            parts_run=[words],
            parts_not_run=[words],
            cost_by_part={words: 1.0},
        ),
    )


def test_a_pupils_words_cannot_break_the_page():
    page = render(*hostile(SCRIPT))
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page

    # Words that would close an attribute and open a tag of their own are escaped too.
    for words in (SCRIPT, ATTRIBUTE):
        page = render(*hostile(words))
        assert "<script" not in page.lower() and "<img" not in page.lower()
        assert escape(words) in page


def test_the_report_has_no_long_dashes_and_no_year_groups():
    pages = [
        render(every_kind_of_result(), full_run(), meta()),
        render(every_kind_of_result(), full_run(), meta(free=True, cost=0.0, cost_by_part={})),
        render(
            every_kind_of_result(),
            full_run(),
            meta(parts_not_run=["2"], cost=None, cost_by_part={"1": 2.0}),
        ),
        render([], run(lessons=[]), {}),
    ]
    for page in pages:
        assert EM_DASH not in page and EN_DASH not in page and "Year " not in page
    assert "14 year olds" in text(pages[0]) and "16 year olds" in text(pages[0])


def test_the_page_stands_alone_and_fits_a_phone():
    page = render(every_kind_of_result(), full_run(), meta())
    lowered = page.lower()

    for outside in ("<script", "<link", "@import", "url(", " src=", "http:", "https:"):
        assert outside not in lowered, outside
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in page
    assert "<style>" in page
    # Every table scrolls inside a box of its own, so the page never scrolls sideways.
    assert page.count("<table") >= 3
    assert page.count("<table") == page.count('<div class="scroll"><table')
    # No coloured stripe down the side of anything.
    assert "border-left" not in page


def test_a_note_under_t8s_table_keeps_the_table():
    table = (
        "Subject | T1 | T2 | T3 | T4 | T5\n"
        "maths | pass | pass (9 of 10) | pass | pass | pass\n"
        "T2 counts only the right answers the writer wrote: 3 stand-in lines were left out."
    )
    page = render([result("T8", "pass", detail=table)], run(), meta())
    passed = re.search(r'<section id="passed".*?</section>', page, flags=re.S).group(0)
    assert passed.count("<table") == 1
    assert passed.index("</table>") < passed.index("3 stand-in lines were left out.")
    assert row(page, "passed", "maths") == "maths pass pass (9 of 10) pass pass pass"


def test_save_writes_the_page_and_the_results(tmp_path):
    evidence = Evidence("QX7RT", "full-class", "x = 6", "Yes, x = 6 is right!", "Marked right.")
    results = [result("T1", "fail", evidence=[evidence])]
    data = run(turns=[turn("QX7RT", said="x = 6", reply="Yes, x = 6 is right!")])
    # A date as the runner may hand it, which JSON does not take as it is.
    run_meta = meta(date=date(2026, 11, 22))
    folder = tmp_path / "school-day-2026-11-22"

    path = save(folder, results, data, run_meta)

    assert path == folder / "report.html"
    assert path.read_text(encoding="utf-8") == render(results, data, run_meta)
    saved = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    assert set(saved) == {"meta", "results", "data"}
    assert saved["results"][0]["code"] == "T1" and saved["results"][0]["outcome"] == "fail"
    assert saved["results"][0]["evidence"][0]["said"] == "x = 6"
    assert saved["meta"]["date"] == "2026-11-22"
    assert saved["meta"]["cost_by_part"] == {"1": 6.0, "2": 9.0}
    assert saved["data"]["turns"][0]["said"] == "x = 6"
    assert saved["data"]["lessons"][0]["key"] == "full-class"
    assert saved["data"]["sent"] == []


def test_a_page_that_fails_to_render_loses_nothing_of_the_run(tmp_path, monkeypatch):
    def broken(*args):
        raise ValueError("the page broke")

    monkeypatch.setattr(report, "render", broken)
    with pytest.raises(ValueError):
        save(tmp_path, [result("T1", "pass")], run(), meta())
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved["results"][0]["code"] == "T1"
    assert not (tmp_path / "report.html").exists()
