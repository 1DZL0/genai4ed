"""The checks on the teacher's side, the pupil's side and the system (the spec's C1 to C11, U1
to U4 and S1 to S4), and run_all. Each check is worked out from a run's data alone, built here
by hand as a small RunData, and each is shown to pass on a good case, to fail on a bad one and,
where it applies, to say "did not come up" when the moment it needs never happened. No
database, no platform and no model.

What the teacher did comes from the runner's log of it in the run's events, in the shapes
checks.EVENTS documents; the pupils' side from the driver's log of what they sent."""

import itertools
import re
from datetime import UTC, datetime, timedelta

import pytest

from app.agent.student_mode import HELD_BACK, INTENTS
from bench.pupils import CANNED
from bench.school import driver
from bench.school.checks import (
    EVENTS,
    EVERY_EVENT,
    FULL_CLASS,
    PLANS,
    SCHOOL_CHECKS,
    STEPS_ASKED,
    TEACHING_CHECKS,
    WITH_TEXT,
    c1,
    c2,
    c3,
    c4,
    c5,
    c6,
    c7,
    c8,
    c9,
    c10,
    c11,
    run_all,
    s1,
    s2,
    s3,
    s4,
    u1,
    u2,
    u3,
    u4,
)
from bench.school.checks_extra import EXTRA_CHECKS
from bench.school.collect import LessonFacts, RunData, Turn
from bench.school.driver import Sent
from bench.school.lessons import GROUP_LESSONS, PART_ONE
from bench.school.report import REACHED_BY
from bench.school.teacher import Drafted

START = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
_numbers = itertools.count(1)
DRAFTED = Drafted("lesson-1", 1)
HINT = "Give them a hint about the first step."


def _next() -> int:
    return next(_numbers)


def at(seconds: float) -> str:
    """The moment `seconds` after nine o'clock on the day, as the runner writes one."""
    return (START + timedelta(seconds=seconds)).isoformat()


def turn(
    pupil: str = "9S-01",
    *,
    line: str | None = None,
    session: str = "S1",
    said: str = "",
    reply_text: str = "",
    outcome: str = "ok",
    manifest: dict | None = None,
    request: dict | None = None,
    helped: bool | None = None,
    when: str | None = None,
) -> Turn:
    """A tutor's turn as collect gives one: by default a reply that wrote a line of its own and
    went out, made with no guidance and no attached text."""
    n = _next()
    return Turn(
        id=f"turn-{n}",
        session_id=session,
        pupil=pupil,
        model="model-x",
        prompt_version="p-1",
        manifest={
            "step_index": 0,
            "pitch": False,
            "memory_lines": [],
            "guidance_ids": [],
            "material_ids": [],
            **(manifest or {}),
        },
        reply={},
        conflicts=[],
        outcome=outcome,
        leak="passed",
        latency_ms=1200,
        said=said,
        reply_text=reply_text or f"reply {n}",
        agent_line_id=line if line is not None else f"line-{n}",
        at=when or at(n),
        request=request if request is not None else {"text": said or None, "guidance": None},
        helped=helped,
    )


def sent(
    pupil: str = "9S-01",
    beat: str = "right",
    text: str = "",
    *,
    line: str | None = None,
    session: str = "S1",
    status: int = 200,
    step: int = 0,
    tries: int = 0,
    lines: int = 4,
    when: float | None = None,
    seconds: float = 3.0,
) -> Sent:
    """A request a pupil made, as the driver logs it. Answered (200), it carries the view that
    came back with it: the step, the wrong tries there and how many lines the page shows."""
    n = _next()
    answered = status == 200
    return Sent(
        pupil=pupil,
        kind="average",
        session_id=session,
        beat=beat,
        text=text,
        status=status,
        seconds=seconds,
        agent_line_id=line,
        at=at(n if when is None else when),
        fallback=False,
        step_index=step if answered else None,
        wrong_tries=tries if answered else None,
        lines=lines if answered else None,
    )


def replied(
    pupil: str,
    beat: str,
    text: str = "",
    *,
    session: str = "S1",
    step: int = 0,
    tries: int = 0,
    lines: int = 4,
    when: float | None = None,
    seconds: float = 3.0,
    **turn_fields,
) -> tuple[Sent, Turn]:
    """A pupil's message and the tutor's turn that answered it, tied by the line it wrote."""
    line = f"line-{_next()}"
    said = text or INTENTS.get(beat.removeprefix("button:"), "")
    return (
        sent(
            pupil,
            beat,
            text,
            line=line,
            session=session,
            step=step,
            tries=tries,
            lines=lines,
            when=when,
            seconds=seconds,
        ),
        turn(pupil, line=line, session=session, said=said, **turn_fields),
    )


def brief(subject: str, age: int | None, steps: int, rules: dict | None = None) -> dict:
    return {
        "subject": subject,
        "age": age,
        "steps": [{"name": f"part {n}"} for n in range(1, steps + 1)],
        "rules": dict(rules or {}),
    }


def lesson(
    key: str = FULL_CLASS,
    session: str = "S1",
    subject: str = "maths",
    *,
    age: int = 14,
    shown: dict | None = None,
    rules: dict | None = None,
    drafted: Drafted | None = None,
) -> LessonFacts:
    """A lesson of the run. Set up from an earlier run's brief unless `drafted` says how
    drafting it went."""
    return LessonFacts(
        key=key,
        session_id=session,
        subject=subject,
        age=age,
        steps=4,
        rules=dict(rules or {}),
        brief=shown if shown is not None else brief(subject, age, 4, rules),
        teacher="sd-maths",
        drafted=drafted,
    )


def who(kind: str = "average", **flags) -> dict:
    """A pupil of the cast, as the driver describes one."""
    return {
        "name": "pupil",
        "kind": kind,
        "steer": None,
        "eal": False,
        "note_target": False,
        "guide_target": False,
        "joins_after_s": 0,
        "signs_back_in": False,
        **flags,
    }


def event(what: str, **fields) -> dict:
    """What the runner logs of one thing the teacher did: by default the platform took it."""
    return {"what": what, "status": 200, "at": at(_next()), **fields}


def alert(
    pupil: str, kind: str = "teacher_requested", *, status: str = "open", aid: str = ""
) -> dict:
    return {
        "id": aid or f"alert-{_next()}",
        "session_id": "S1",
        "pupil": pupil,
        "kind": kind,
        "status": status,
        "summary": "",
        "payload": {},
        "at": at(_next()),
        "acknowledged_at": at(_next()) if status == "acknowledged" else None,
    }


def outcome_of(
    pupil: str, session: str = "S1", *, status: str = "suggested", confirmed: dict | None = None
) -> dict:
    return {
        "session_id": session,
        "pupil": pupil,
        "status": status,
        "suggested": {},
        "confirmed": confirmed,
        "confirmed_at": at(_next()) if status == "confirmed" else None,
    }


def run(
    *,
    lessons=None,
    turns=(),
    sent=(),
    events=(),
    alerts=(),
    access=(),
    outcomes=(),
    notes=(),
    guidance=(),
    teacher_replies=(),
    view_seconds=(),
    errors=(),
    cast=None,
) -> RunData:
    """A run with these records and nothing else; the full class's lesson, S1, unless given."""
    return RunData(
        lessons=list(lessons) if lessons is not None else [lesson()],
        turns=list(turns),
        sent=list(sent),
        events=list(events),
        alerts=list(alerts),
        access=list(access),
        outcomes=list(outcomes),
        notes=list(notes),
        note_lines={},
        evidence_subject={},
        guidance=list(guidance),
        states=[],
        teacher_replies=list(teacher_replies),
        view_seconds=list(view_seconds),
        errors=list(errors),
        cast=dict(cast or {}),
    )


JARGON = re.compile(
    r"\b(manifest|beat|turns?|withheld|regenerated|disclosure|judgment|session|status|"
    r"exception|drilldown|median|percentile)\b|_",
    re.IGNORECASE,
)


def assert_plain(result) -> None:
    """Everything the result says is one plain line, for the platform's owner to read."""
    for words in (result.title, result.meaning, result.detail, *(e.note for e in result.evidence)):
        assert words.strip() == words and "\n" not in words, words
        assert not JARGON.search(words) and "None" not in words, words
        assert not re.search(r"\byear\s*\d", words, re.IGNORECASE), words
        assert chr(0x2014) not in words and chr(0x2013) not in words, words


# ---------- what every check shares ----------


@pytest.mark.parametrize("check", SCHOOL_CHECKS, ids=lambda check: check.__name__)
def test_every_check_says_it_did_not_come_up_when_nothing_happened(check):
    """Never a pass for a run where nothing happened: the anti-goal is a check that always
    passes."""
    result = check(run())
    assert result.outcome == "did not come up"
    assert result.detail
    assert result.evidence == []
    assert_plain(result)
    assert len(result.title) <= 60 and result.meaning.endswith(".")


def test_the_checks_are_the_specs_in_its_order():
    codes = [check(run()).code for check in SCHOOL_CHECKS]
    assert codes == [
        *(f"C{n}" for n in range(1, 12)),
        *(f"U{n}" for n in range(1, 5)),
        *(f"S{n}" for n in range(1, 5)),
    ]
    assert [check.__name__ for check in SCHOOL_CHECKS] == [code.lower() for code in codes]


def test_run_all_runs_every_check_in_the_specs_order():
    # Teaching, pitching and memory (18), these (19), then the added parts (18).
    every = [*TEACHING_CHECKS, *SCHOOL_CHECKS, *EXTRA_CHECKS]
    assert (len(TEACHING_CHECKS), len(SCHOOL_CHECKS), len(EXTRA_CHECKS)) == (18, 19, 18)
    results = run_all(run())
    assert [r.code for r in results] == [check(run()).code for check in every]
    assert len(results) == 55 and len({r.code for r in results}) == 55
    # Each result is its own check's, worked out on the run it is given.
    data = run(errors=["9S-01, right: 500 Internal Server Error"], cast={"9S-01": who()})
    found = {r.code: r for r in run_all(data)}
    assert found["S1"].outcome == "fail" and found["S1"].evidence[0].pupil == "9S-01"
    assert found["T1"].outcome == "did not come up"


def test_the_report_knows_which_part_reaches_every_check():
    """The report says which part to run again for a check that did not come up."""
    assert {result.code for result in run_all(run())} <= set(REACHED_BY)


def test_the_teachers_actions_have_names_of_their_own():
    """The runner logs the teacher's actions beside the driver's own notes and the teacher's
    uploads: a name they share would read one as the other (the report reads "paused" as a
    pupil refused)."""
    others = {"paused", "rate limited", "unavailable", "time up", "closed", "upload"}
    others.add(driver.PUPILS_STOPPED)
    assert not set(EVENTS) & others
    assert EVERY_EVENT == ("what", "at", "status")
    for keys in EVENTS.values():
        assert not set(keys) & set(EVERY_EVENT)
    # The driver's notes the checks read are the driver's.
    assert {"paused", "rate limited", "unavailable"} <= set(driver._RETRIES)


def test_the_lessons_the_checks_name_are_the_days():
    plans = {plan.key: plan for group in GROUP_LESSONS.values() for plan in group}
    assert FULL_CLASS == PART_ONE.key == "full-class"
    assert {plans[key].subject.lower() for key in WITH_TEXT} == {"english", "history"}
    for key in WITH_TEXT:
        assert any(name.endswith(".txt") for name in plans[key].attachments)


def test_each_lesson_asks_for_the_number_of_steps_c1_holds_it_to():
    """C1 holds each drafted lesson to the number of steps the teacher's words ask for."""
    assert STEPS_ASKED == {
        "full-class": 4,
        "a-maths": 3,
        "a-english": 4,
        "a-maths-2": 3,
        "b-history": 4,
        "b-science": 4,
        "c-english": 3,
    }
    assert set(STEPS_ASKED) == set(PLANS)
    named = {3: "three", 4: "four"}
    for key, steps in STEPS_ASKED.items():
        words = PLANS[key].words.lower()
        assert f"{named[steps]} steps" in words or f"{named[steps]} parts" in words, key
        # And no other number of steps or parts.
        others = [n for n in ("two", "three", "four", "five", "six") if n != named[steps]]
        assert not any(f"{n} steps" in words or f"{n} parts" in words for n in others), key


# ---------- C1: each lesson is drafted as asked ----------


def test_c1_passes_on_a_good_run():
    data = run(
        lessons=[
            lesson(shown=brief("Mathematics", 14, 4), drafted=DRAFTED),
            # The subject as the agent wrote it, with the one asked for among its words, and a
            # draft written as a change to a lesson the teacher had.
            lesson(
                "c-english",
                "S2",
                "English",
                age=12,
                shown=brief("English Literature", 12, 3),
                drafted=Drafted("lesson-2", 2, "written as a change to Poems"),
            ),
            # Set up from an earlier run's brief: not drafted here, so not C1's business.
            lesson("a-maths", "S3", shown=brief("History", 9, 7)),
        ]
    )
    result = c1(data)
    assert result.outcome == "pass"
    assert result.evidence == []
    assert result.detail == (
        "Lessons drafted from the teacher's words with the age, subject and number of steps "
        "asked for: 2 of 2."
    )


def test_c1_fails_on_a_bad_run():
    data = run(
        lessons=[
            lesson(shown=brief("maths", 14, 4), drafted=DRAFTED),
            lesson("a-maths", "S2", shown=brief("maths", 14, 3), drafted=DRAFTED),
            lesson("b-history", "S3", shown=brief("Geography", 16, 4), drafted=DRAFTED),
            lesson("b-science", "S4", shown=brief("science", 16, 6), drafted=DRAFTED),
            lesson("c-english", "S5", shown=brief("", None, 3), drafted=DRAFTED),
            # Four steps where the teacher asked for three: one of the usual counts, not theirs.
            lesson("a-maths-2", "S6", shown=brief("maths", 13, 4), drafted=DRAFTED),
            lesson(
                "a-english",
                "",
                shown={},
                drafted=Drafted(None, 3, "The class agent did not draft the lesson."),
            ),
        ]
    )
    result = c1(data)
    assert result.outcome == "fail"
    assert [e.lesson for e in result.evidence] == [
        "a-maths",
        "b-history",
        "b-science",
        "c-english",
        "a-maths-2",
        "a-english",
    ]
    age, subject, steps, blank, exact, missing = (e.note for e in result.evidence)
    assert "the age is 14 where 13 was asked for" in age
    assert 'the subject is "Geography" where history was asked for' in subject
    assert "it has 6 steps where 4 were asked for" in steps
    assert "it gives no age where 12" in blank and "it gives no subject where English" in blank
    assert exact == (
        "The lesson the class agent drafted is not as the teacher asked: it has 4 steps where 3 "
        "were asked for."
    )
    assert missing == "The class agent did not draft the lesson."
    assert result.detail.endswith("asked for: 1 of 7.")
    assert_plain(result)


def test_c1_holds_a_lesson_the_days_plan_does_not_have_to_its_own_facts():
    asked = lesson("extra", "S1", "science", age=15, shown=brief("Science", 15, 3), drafted=DRAFTED)
    assert c1(run(lessons=[asked])).outcome == "pass"
    older = lesson("extra", "S1", "science", age=15, shown=brief("Science", 14, 3), drafted=DRAFTED)
    assert c1(run(lessons=[older])).outcome == "fail"
    # No words of the day's say how many steps it should have, so its steps are not judged.
    long = lesson("extra", "S1", "science", age=15, shown=brief("Science", 15, 9), drafted=DRAFTED)
    assert c1(run(lessons=[long])).outcome == "pass"


def test_c1_did_not_come_up():
    # Every lesson set up from an earlier run's briefs.
    data = run(lessons=[lesson(), lesson("c-english", "S2", "English", age=12)])
    result = c1(data)
    assert result.outcome == "did not come up"
    assert "earlier run" in result.detail


# ---------- C2: the same questions, and a note to go gently ----------

GENTLE = "8A-06"


def same_questions(adapt, drafted: Drafted | None = DRAFTED) -> LessonFacts:
    rules = {} if adapt == "unset" else {"adapt_to_student": adapt}
    return lesson("c-english", "S5", "English", age=12, rules=rules, drafted=drafted)


def note(until: str, when: str, pupil: str = GENTLE) -> dict:
    return {"teacher": "sd-a", "pupil": pupil, "text": "Keep it short.", "until": until, "at": when}


def gently(when: str = "2026-11-21T10:00:00+00:00", **more) -> dict:
    return event("go gently", pupil=GENTLE, at=when, **more)


GROUP_A = {GENTLE: who("struggling", note_target=True), "8A-01": who("strong")}
KEPT = note("2026-11-27", "2026-11-21T10:00:05+00:00")


def test_c2_passes_on_a_good_run():
    data = run(lessons=[same_questions(False)], cast=GROUP_A, events=[gently()], notes=[KEPT])
    result = c2(data)
    assert result.outcome == "pass"
    assert result.evidence == []
    assert "asks everyone the same questions" in result.detail
    assert "kept for the week asked: 1 of 1" in result.detail


def test_c2_takes_the_day_it_was_asked_or_the_day_it_was_kept():
    # Asked just before midnight and kept just after: either day's week will do.
    data = run(
        lessons=[same_questions(False)],
        cast=GROUP_A,
        events=[gently("2026-11-21T23:59:58+00:00")],
        notes=[note("2026-11-28", "2026-11-22T00:00:01+00:00")],
    )
    assert c2(data).outcome == "pass"
    # The other way round: kept on the day it was asked by the platform's clock, and stamped
    # just after midnight by the database's.
    data = run(
        lessons=[same_questions(False)],
        cast=GROUP_A,
        events=[gently("2026-11-21T23:59:58+00:00")],
        notes=[note("2026-11-27", "2026-11-22T00:00:01+00:00")],
    )
    assert c2(data).outcome == "pass"


def test_c2_reads_the_rule_from_the_brief_when_the_lessons_rules_leave_it_out():
    facts = same_questions("unset")
    facts.brief["rules"] = {"adapt_to_student": False}
    data = run(lessons=[facts], cast=GROUP_A, events=[gently()], notes=[KEPT])
    assert c2(data).outcome == "pass"


def test_c2_fails_on_a_bad_run():
    # The rule left to the teacher's setting, and the note kept a day too long.
    data = run(
        lessons=[same_questions(None)],
        cast=GROUP_A,
        events=[gently()],
        notes=[note("2026-11-28", "2026-11-21T10:00:05+00:00")],
    )
    result = c2(data)
    assert result.outcome == "fail"
    rule, kept = result.evidence
    assert (rule.pupil, rule.lesson) == ("", "c-english")
    assert "says nothing about it, so the teacher's setting decides" in rule.note
    assert kept.pupil == GENTLE
    assert "kept until Saturday 28 November" in kept.note
    assert "ends on Friday 27 November" in kept.note
    assert_plain(result)


def test_c2_fails_when_the_teacher_asked_and_no_note_was_kept():
    data = run(lessons=[same_questions(True)], cast=GROUP_A, events=[gently(status=500)])
    result = c2(data)
    assert result.outcome == "fail"
    rule, kept = result.evidence
    assert "lets the tutor pitch each step for each pupil" in rule.note
    assert kept.pupil == GENTLE and "no note was kept" in kept.note and "500" in kept.note


def test_c2_did_not_come_up():
    # Group C's lesson set up from an earlier run, and no note asked for.
    data = run(lessons=[same_questions(False, drafted=None)], cast=GROUP_A)
    result = c2(data)
    assert result.outcome == "did not come up"
    assert "not drafted from the teacher's words" in result.detail
    assert "did not ask to go gently" in result.detail
    # One half passes and the other never happened: still not a pass.
    assert c2(run(lessons=[same_questions(False)])).outcome == "did not come up"
    # Group C's lesson was not drafted at all (C1 says so), though the note was kept.
    data = run(
        lessons=[same_questions(False, drafted=Drafted(None, 3, "did not draft"))],
        cast=GROUP_A,
        events=[gently()],
        notes=[KEPT],
    )
    assert c2(data).outcome == "did not come up"


def test_c2_fails_when_one_half_fails_and_the_other_never_happened():
    assert c2(run(lessons=[same_questions(None)])).outcome == "fail"


# ---------- C3: guidance reaches the pupil's tutor ----------


def kept_guidance(pupil: str, text: str = HINT, *, gid: str, session: str = "S6") -> dict:
    return {
        "id": gid,
        "session_id": session,
        "pupil": pupil,
        "payload": {"text": text, "shown_to_student": False},
        "at": "2026-11-21T09:03:00+00:00",
    }


def guided(pupil: str, text: str = HINT, **more) -> dict:
    return event("guided", pupil=pupil, session_id="S6", text=text, **more)


A_MATHS = [lesson("a-maths", "S6", age=13)]


def test_c3_passes_on_a_good_run():
    # Answered at once, and stamped before the guidance on another clock: times are never
    # compared.
    answered = turn(
        "8A-05",
        session="S6",
        request={"text": None, "intent": None, "guidance": f"  {HINT} "},
        when="2026-11-21T09:02:59+00:00",
    )
    # The tutor could not answer at once: its next reply to the pupil was made with it.
    later = turn("8A-02", session="S6", manifest={"guidance_ids": ["G2"]})
    data = run(
        lessons=A_MATHS,
        turns=[answered, later],
        guidance=[
            kept_guidance("8A-05", gid="G1"),
            kept_guidance("8A-02", "Ask them to check their working.", gid="G2"),
        ],
        events=[guided("8A-05")],
    )
    result = c3(data)
    assert result.outcome == "pass"
    assert result.detail.endswith("2 of 2.")


def test_c3_fails_on_a_bad_run():
    data = run(
        lessons=A_MATHS,
        turns=[
            # The guidance reached another pupil's tutor.
            turn("8A-04", session="S6", request={"text": None, "guidance": HINT}),
            # This pupil's tutor had older guidance only.
            turn("8A-05", session="S6", manifest={"guidance_ids": ["G0"]}),
        ],
        guidance=[kept_guidance("8A-05", gid="G1")],
        events=[guided("8A-05"), guided("8A-03", "Slow down for them.")],
    )
    result = c3(data)
    assert result.outcome == "fail"
    reached, lost = result.evidence
    assert (reached.pupil, reached.lesson) == ("8A-05", "a-maths")
    assert f'"{HINT}" was kept, and no reply' in reached.note
    assert lost.pupil == "8A-03" and "it was not kept" in lost.note
    assert result.detail.endswith("0 of 2.")
    assert_plain(result)


def test_c3_fails_when_the_platform_refused_the_guidance():
    result = c3(run(events=[guided("8A-05", status=500)]))
    assert result.outcome == "fail" and "500" in result.evidence[0].note


def test_c3_did_not_come_up():
    assert (
        c3(run(lessons=A_MATHS, turns=[turn("8A-05", session="S6")])).outcome == "did not come up"
    )
    # Refused because the lesson had ended: the guidance never happened.
    result = c3(run(events=[guided("8A-05", status=409)]))
    assert result.outcome == "did not come up"


# ---------- C4: an outcome for every pupil who wrote ----------


TWO_LESSONS = [lesson(), lesson("a-maths", "S2", age=13)]


def test_c4_passes_on_a_good_run():
    data = run(
        lessons=TWO_LESSONS,
        sent=[
            sent("9S-01", "right", "x = 5", line="L1"),
            sent("9S-02", "button:example", line="L2"),
            # Opened only: an opening alone is not taking part, so it has no outcome.
            sent("9S-03", "open", line="L3"),
            # Refused once the lesson had closed.
            sent("9S-04", "right", "x = 5", status=409),
            # Wrote in a lesson nobody summed up.
            sent("8A-01", "right", "15", line="L4", session="S2"),
        ],
        outcomes=[outcome_of("9S-01"), outcome_of("9S-02", status="confirmed")],
    )
    result = c4(data)
    assert result.outcome == "pass"
    assert "2 of 2, in 1 lesson" in result.detail


def test_c4_fails_on_a_bad_run():
    data = run(
        lessons=TWO_LESSONS,
        sent=[
            sent("9S-01", "right", "x = 5", line="L1"),
            sent("9S-02", "wrong", "x = 7", line="L2"),
            sent("8A-01", "right", "15", line="L4", session="S2"),
        ],
        # 9S-02's outcome is for another lesson, and the second lesson's summary failed.
        outcomes=[outcome_of("9S-01"), outcome_of("9S-02", session="S2")],
        events=[event("summary", session_id="S2", status=503)],
    )
    result = c4(data)
    assert result.outcome == "fail"
    assert [(e.pupil, e.lesson) for e in result.evidence] == [
        ("9S-02", FULL_CLASS),
        ("8A-01", "a-maths"),
    ]
    assert "no outcome for them" in result.evidence[0].note
    assert "503" in result.evidence[1].note
    assert "1 of 3, in 2 lessons" in result.detail
    assert_plain(result)


def test_c4_did_not_come_up():
    # Pupils wrote, and no lesson had its summary written.
    result = c4(run(sent=[sent("9S-01", "right", "x = 5", line="L1")]))
    assert result.outcome == "did not come up"
    assert result.detail == "No lesson had its summary written."
    # A summary, and nobody who wrote.
    data = run(sent=[sent("9S-01", "open", line="L1")], events=[event("summary", session_id="S1")])
    result = c4(data)
    assert result.outcome == "did not come up"
    assert result.detail == "No pupil wrote in a lesson whose summary was written."


# ---------- C5: who needs me names the right pupils ----------

UPSET, ASKER = "9S-22", "9S-23"
CLASS = {UPSET: who("upset"), ASKER: who("ask_teacher"), "9S-01": who("strong")}


def needs(*, upset_at: float = 60, asked_at: float = 90) -> list[Sent]:
    return [
        sent(
            UPSET, "stressed", "im so stressed about the test", line="L1", when=upset_at, seconds=8
        ),
        sent(ASKER, "ask_teacher", line="L2", when=asked_at, seconds=0.2),
    ]


def who_needs_me(reply: str, *, when: float = 240, session: str | None = "S1", **more) -> dict:
    return event(
        "asked",
        session_id=session,
        question="Who needs me right now?",
        reply=reply,
        at=at(when),
        **more,
    )


def test_c5_passes_on_a_good_run():
    data = run(
        # An upset pupil in another lesson need not be named.
        cast={**CLASS, "7C-06": who("upset")},
        sent=[
            *needs(),
            sent("7C-06", "stressed", "test friday", line="L9", session="S3", when=100),
        ],
        events=[
            who_needs_me(f"{UPSET.lower()} is worried about a test,\nand {ASKER} asked for you."),
            # Another question: not C5's business.
            event("asked", session_id="S1", question="How many of them finished?", reply="12."),
        ],
    )
    result = c5(data)
    assert result.outcome == "pass"
    assert result.detail.endswith("1 of 1.")


def test_c5_judges_a_question_logged_without_its_lesson():
    data = run(cast=CLASS, sent=needs(), events=[who_needs_me(f"{UPSET}, {ASKER}", session=None)])
    assert c5(data).outcome == "pass"


def test_c5_fails_on_a_bad_run():
    # Only the pupil who asked is named, beside a name that only starts with the upset pupil's.
    reply = f"{ASKER} asked for you.\n{UPSET}0 is doing fine."
    result = c5(run(cast=CLASS, sent=needs(), events=[who_needs_me(reply)]))
    assert result.outcome == "fail"
    (missed,) = result.evidence
    assert missed.lesson == FULL_CLASS
    # The reply quoted on one line, its own full stop ending the sentence.
    assert missed.note == (
        'The teacher asked "Who needs me right now?", and the class agent replied: '
        f'"{ASKER} asked for you. {UPSET}0 is doing fine." It did not name {UPSET} (upset about '
        "a test)."
    )
    assert_plain(result)
    # A reply with no full stop of its own gets one after the quote.
    result = c5(run(cast=CLASS, sent=needs(), events=[who_needs_me(f"only {ASKER}")]))
    assert f'replied: "only {ASKER}". It did not name {UPSET}' in result.evidence[0].note


def test_c5_fails_when_no_reply_came():
    result = c5(run(cast=CLASS, sent=needs(), events=[who_needs_me("", status=503)]))
    assert result.outcome == "fail"
    (missed,) = result.evidence
    assert "no reply came" in missed.note and "503" in missed.note
    assert missed.note.endswith(
        f"It did not name {UPSET} (upset about a test) or {ASKER} (asked for the teacher)."
    )


def test_c5_did_not_come_up():
    assert c5(run(cast=CLASS, sent=needs())).outcome == "did not come up"
    # Asked while the upset pupil's message still waited for its reply, and before the other
    # pupil asked for the teacher: nobody needed them yet.
    data = run(
        cast=CLASS,
        sent=needs(upset_at=230, asked_at=245),
        events=[who_needs_me("Nobody needs you right now.", when=235)],
    )
    result = c5(data)
    assert result.outcome == "did not come up"
    assert "before any pupil" in result.detail


# ---------- C6: alerts can be dealt with ----------


def dealt_with(aid: str, **more) -> dict:
    return event("acknowledged", session_id="S1", exception_id=aid, **more)


def test_c6_passes_on_a_good_run():
    data = run(
        alerts=[
            alert(ASKER, status="acknowledged", aid="A1"),
            alert(UPSET, "safeguarding", status="acknowledged", aid="A2"),
            # Cleared by the pupil's own progress before the teacher pressed.
            alert("9S-10", "struggling", status="resolved", aid="A3"),
            # Never dealt with: not C6's business.
            alert("9S-11", "off_task", aid="A4"),
        ],
        # A1 pressed twice.
        events=[dealt_with(aid) for aid in ("A1", "A2", "A3", "A1")],
    )
    result = c6(data)
    assert result.outcome == "pass"
    assert "2 of 2" in result.detail
    assert "1 alert the pupil's own progress had already cleared" in result.detail


def test_c6_fails_on_a_bad_run():
    data = run(
        alerts=[
            alert(ASKER, status="acknowledged", aid="A1"),
            alert(UPSET, "safeguarding", aid="A2"),
        ],
        events=[dealt_with("A1"), dealt_with("A2", status=500), dealt_with("A9")],
    )
    result = c6(data)
    assert result.outcome == "fail"
    still, unknown = result.evidence
    assert (still.pupil, still.lesson) == (UPSET, FULL_CLASS)
    assert "a wellbeing alert about this pupil, and it is still on their list" in still.note
    assert "500" in still.note
    assert unknown.pupil == "" and "the lesson's records do not have" in unknown.note
    assert "1 of 3" in result.detail
    assert_plain(result)


def test_c6_did_not_come_up():
    assert c6(run(alerts=[alert(ASKER)])).outcome == "did not come up"
    data = run(
        alerts=[alert("9S-10", "struggling", status="resolved", aid="A3")],
        events=[dealt_with("A3")],
    )
    result = c6(data)
    assert result.outcome == "did not come up"
    assert "already been cleared" in result.detail


# ---------- C7: reading a conversation is logged ----------


def access(pupil: str, action: str = "transcript_drilldown", session: str = "S1") -> dict:
    return {
        "teacher": "sd-maths",
        "session_id": session,
        "pupil": pupil,
        "action": action,
        "detail": {},
        "at": at(_next()),
    }


def read(pupil: str, **more) -> dict:
    return event("read conversation", session_id="S1", pupil=pupil, **more)


def test_c7_passes_on_a_good_run():
    data = run(
        events=[read("9S-04"), read("9S-04")],
        access=[access("9S-03", "guide_student"), access("9S-04")],
    )
    result = c7(data)
    assert result.outcome == "pass" and result.detail.endswith("1 of 1.")


def test_c7_fails_on_a_bad_run():
    data = run(
        events=[read("9S-04"), read("9S-05")],
        # Another action on the one, and a read of the other in another lesson.
        access=[access("9S-04", "guide_student"), access("9S-05", session="S2")],
    )
    result = c7(data)
    assert result.outcome == "fail"
    assert [(e.pupil, e.lesson) for e in result.evidence] == [
        ("9S-04", FULL_CLASS),
        ("9S-05", FULL_CLASS),
    ]
    assert "record does not show it" in result.evidence[0].note
    assert_plain(result)


def test_c7_did_not_come_up():
    assert c7(run(access=[access("9S-04")])).outcome == "did not come up"


# ---------- C8: pause, resume and extra minutes ----------


def pause_and_resume(*, paused: float = 300, resumed: float = 360) -> list[dict]:
    """A pause in force a second after it was pressed, and a resume pressed a minute later."""
    return [
        event("teacher paused", session_id="S1", at=at(paused), done=at(paused + 1)),
        event("teacher resumed", session_id="S1", at=at(resumed), done=at(resumed + 1)),
    ]


def turned_away(pupil: str, when: float, beat: str = "right") -> dict:
    """The driver's note of a pupil's request refused because the lesson was paused."""
    return {
        "what": "paused",
        "pupil": pupil,
        "beat": beat,
        "at": at(when),
        "detail": "Session is paused.",
    }


def extended(
    before: str | None = "2026-11-21T09:40:00+00:00",
    after: str | None = "2026-11-21T09:50:00+00:00",
    *,
    minutes: int = 10,
    when: float = 420,
    **more,
) -> dict:
    return event(
        "extended",
        session_id="S1",
        minutes=minutes,
        closes_before=before,
        closes_after=after,
        at=at(when),
        **more,
    )


def test_c8_passes_on_a_good_run():
    data = run(
        lessons=TWO_LESSONS,
        sent=[
            sent("9S-04", "open", line="L0", when=10),
            # Sent before the pause took hold and answered during it: taken, rightly.
            sent("9S-01", "wrong", "x = 7", line="L1", when=295, seconds=12),
            # Sent while the pause was on its way: it could go either way.
            sent("9S-05", "not_sure", "idk", line="L5", when=300.5, seconds=3),
            # Ask my teacher still works while the lesson is paused.
            sent("9S-02", "ask_teacher", line="L1", when=320, seconds=0.2),
            # Sent while paused and answered after the resume went: either way, again.
            sent("9S-06", "wrong", "x = 9", line="L6", when=358, seconds=5),
            # Sent while the resume was on its way: it could go either way.
            sent("9S-03", "right", "x = 5", line="L2", when=360.5, seconds=4),
            # After the resume.
            sent("9S-01", "right", "x = 5", line="L3", when=370, seconds=4),
            # A pupil of another lesson, writing at the same time.
            sent("8A-01", "right", "15", line="L4", session="S2", when=330, seconds=3),
        ],
        events=[
            *pause_and_resume(),
            turned_away("9S-01", 310),
            turned_away("9S-04", 340, beat="leave"),
            # A pupil of another lesson, paused by its own teacher.
            turned_away("8A-01", 380),
            extended(),
        ],
    )
    result = c8(data)
    assert result.outcome == "pass", result.detail
    assert result.evidence == []
    assert "pupils were turned away 2 times and let through 0 times" in result.detail
    assert "pupils got through 1 time and were turned away as paused 0 times" in result.detail
    assert "as far as it should: 1 of 1" in result.detail


def test_c8_fails_on_a_bad_run():
    data = run(
        sent=[
            sent("9S-04", "open", line="L0", when=10),
            # Sent after the pause took hold, answered before the resume went: taken while paused.
            sent("9S-02", "right", "x = 5", line="L1", when=320, seconds=2),
            sent("9S-01", "right", "x = 5", line="L3", when=370, seconds=4),
        ],
        events=[
            *pause_and_resume(),
            turned_away("9S-01", 310),
            # Still refused as paused after the resume, twice.
            turned_away("9S-04", 380),
            turned_away("9S-04", 385),
            # The end moved by 5 minutes, not 10.
            extended(after="2026-11-21T09:45:00+00:00"),
        ],
    )
    result = c8(data)
    assert result.outcome == "fail"
    taken, still, moved = result.evidence
    assert (taken.pupil, taken.lesson, taken.said) == ("9S-02", FULL_CLASS, "x = 5")
    assert "while the lesson was paused" in taken.note
    assert still.pupil == "9S-04" and "still turned away" in still.note and "2 times" in still.note
    assert moved.pupil == "" and "added 10 minutes" in moved.note
    assert "moved by 5 minutes, from 09:40:00 to 09:45:00" in moved.note
    assert_plain(result)


def test_c8_counts_minutes_added_after_the_time_ran_out_from_when_they_were_added():
    # The lesson's end had passed (09:05) when the teacher added 10 minutes at 09:07, so the new
    # end is 10 minutes after 09:07 (here two seconds later, the platform's own moment).
    late = extended("2026-11-21T09:05:00+00:00", at(420 + 600 + 2), when=420)
    result = c8(run(events=[late]))
    # The pause never happened, so the whole check did not come up, but this part passed.
    assert result.outcome == "did not come up" and result.evidence == []
    assert "as far as it should: 1 of 1" in result.detail
    # Moved by exactly 10 minutes from the old end, though the time had run out: too little.
    short = extended("2026-11-21T09:05:00+00:00", "2026-11-21T09:15:00+00:00", when=420)
    assert c8(run(events=[short])).outcome == "fail"


def test_c8_says_how_far_the_end_moved():
    def moved(after: str) -> str:
        (shown,) = c8(run(events=[extended(after=after)])).evidence
        return shown.note

    assert "the lesson's end did not move, from 09:40:00 to 09:40:00" in moved(
        "2026-11-21T09:40:00+00:00"
    )
    assert "moved by 10 minutes 30 seconds" in moved("2026-11-21T09:50:30+00:00")
    assert "moved back by 5 minutes" in moved("2026-11-21T09:35:00+00:00")
    # Within a second of the minutes added: as far as it should.
    assert c8(run(events=[extended(after="2026-11-21T09:50:00.900000+00:00")])).evidence == []
    # As the teacher's class card writes the end (cards.py, closes_at): UTC, with a Z.
    card = extended("2026-11-21T09:40:00Z", "2026-11-21T09:50:00Z")
    assert "as far as it should: 1 of 1" in c8(run(events=[card])).detail


def test_c8_fails_when_the_minutes_were_not_added_or_the_end_not_shown():
    refused, unseen = c8(run(events=[extended(status=500), extended(None, None)])).evidence
    assert "added 10 minutes, and the platform did not add them" in refused.note
    assert "500" in refused.note
    assert "the lesson's end was not given before and after" in unseen.note


def test_c8_names_what_a_paused_lesson_let_through():
    data = run(
        sent=[
            sent("9S-01", "open", line="L0", when=310, seconds=2),
            sent("9S-02", "leave", line="L1", when=320, seconds=2),
            sent("9S-03", "button:example", line="L2", when=330, seconds=2),
        ],
        events=pause_and_resume(),
    )
    result = c8(data)
    assert result.outcome == "fail"
    opened, moved, pressed = result.evidence
    assert "opened the lesson while it was paused" in opened.note
    assert "moved between steps while the lesson was paused" in moved.note
    assert pressed.said == INTENTS["example"] and "sent this while" in pressed.note


def test_c8_fails_when_the_platform_would_not_pause():
    paused = event("teacher paused", session_id="S1", at=at(300), done=at(301), status=500)
    result = c8(run(events=[paused]))
    assert result.outcome == "fail"
    assert "did not pause it" in result.evidence[0].note and "500" in result.evidence[0].note
    assert result.detail.startswith("The platform did not pause the lesson when the teacher asked.")


def test_c8_fails_when_the_platform_would_not_resume():
    paused, resumed = pause_and_resume()
    resumed["status"] = 500
    data = run(
        sent=[sent("9S-01", "open", line="L0", when=10)],
        events=[paused, resumed, turned_away("9S-01", 310)],
    )
    result = c8(data)
    assert result.outcome == "fail"
    assert [e.note for e in result.evidence] == [
        "The teacher resumed the lesson, and the platform did not resume it. "
        "The platform answered 500."
    ]
    assert "The platform did not resume the lesson when the teacher asked." in result.detail


def test_c8_leaves_out_a_pause_refused_because_the_lesson_had_ended():
    paused, resumed = pause_and_resume()
    paused["status"] = 409
    result = c8(run(events=[paused, resumed]))
    assert result.outcome == "did not come up"
    assert result.detail.startswith("The teacher never paused a lesson.")
    # A resume refused for that reason never happened either.
    paused, resumed = pause_and_resume()
    resumed["status"] = 409
    data = run(
        sent=[sent("9S-01", "open", line="L0", when=10)],
        events=[paused, resumed, turned_away("9S-01", 310)],
    )
    result = c8(data)
    assert result.outcome == "did not come up"
    assert "The teacher never resumed a paused lesson." in result.detail


def test_c8_did_not_come_up():
    assert c8(run()).outcome == "did not come up"
    # Paused and resumed with nobody writing, and minutes added: two parts never happened.
    data = run(
        sent=[sent("9S-01", "open", line="L1", when=10)], events=[*pause_and_resume(), extended()]
    )
    result = c8(data)
    assert result.outcome == "did not come up"
    assert "No pupil tried to write while the lesson was paused." in result.detail
    assert "No pupil wrote once the lesson was resumed." in result.detail
    # Minutes the platform could not add, as the lesson had ended: they never happened.
    result = c8(run(events=[extended(None, None, status=409)]))
    assert result.outcome == "did not come up"
    assert "never added minutes" in result.detail


def test_c8_did_not_come_up_when_one_part_never_happened_and_the_others_passed():
    after = sent("9S-01", "right", "x = 5", line="L3", when=370, seconds=4)
    # Nobody tried to write while the lesson was paused.
    data = run(
        sent=[sent("9S-01", "open", line="L0", when=10), after],
        events=[*pause_and_resume(), extended()],
    )
    result = c8(data)
    assert result.outcome == "did not come up"
    assert "No pupil tried to write while the lesson was paused." in result.detail
    # Nobody wrote once it was resumed.
    data = run(
        sent=[sent("9S-01", "open", line="L0", when=10)],
        events=[*pause_and_resume(), turned_away("9S-01", 310), extended()],
    )
    result = c8(data)
    assert result.outcome == "did not come up"
    assert "No pupil wrote once the lesson was resumed." in result.detail


# ---------- C9: confirmed outcomes reach the pupils ----------

NOTE_FOR_1 = {
    "criteria": [],
    "keep": "You set out your working clearly.",
    "develop": ["Check signs.", ""],
}
NOTE_FOR_2 = {"criteria": [], "keep": "You kept going.", "develop": []}


def on_page(confirmed: dict) -> dict:
    """The result on a pupil's page for an outcome confirmed with this note."""
    develop = [d for d in confirmed["develop"] if d]
    return {
        "total": 0,
        "out_of": 0,
        "criteria": [],
        "comment": None,
        "keep": confirmed["keep"],
        "develop": develop,
    }


def confirmed(pupil: str, **more) -> dict:
    return event("confirmed", session_id="S1", pupil=pupil, **more)


def seen(pupil: str, result, **more) -> dict:
    return event("result seen", session_id="S1", pupil=pupil, result=result, **more)


def test_c9_passes_on_a_good_run():
    data = run(
        outcomes=[
            outcome_of("9S-01", status="confirmed", confirmed=NOTE_FOR_1),
            outcome_of("9S-02", status="confirmed", confirmed=NOTE_FOR_2),
            outcome_of("9S-03", status="confirmed", confirmed=NOTE_FOR_2),
        ],
        events=[
            confirmed("9S-01"),
            confirmed("9S-02"),
            confirmed("9S-03"),
            seen("9S-01", on_page(NOTE_FOR_1)),
            seen("9S-02", on_page(NOTE_FOR_2)),
        ],
    )
    result = c9(data)
    assert result.outcome == "pass"
    assert "marked confirmed: 3 of 3" in result.detail
    assert (
        "2 of 2 read" in result.detail and "1 pupil did not have their page read" in result.detail
    )


def test_c9_fails_on_a_bad_run():
    data = run(
        outcomes=[
            outcome_of("9S-01", status="confirmed", confirmed=NOTE_FOR_1),
            outcome_of("9S-02"),
            outcome_of("9S-03", status="confirmed", confirmed=NOTE_FOR_1),
        ],
        events=[
            confirmed("9S-01"),
            confirmed("9S-02"),
            confirmed("9S-03"),
            confirmed("9S-04"),
            seen("9S-01", None),
            # Another pupil's outcome on this pupil's page.
            seen("9S-03", on_page(NOTE_FOR_2)),
        ],
    )
    result = c9(data)
    assert result.outcome == "fail"
    assert [e.pupil for e in result.evidence] == ["9S-02", "9S-04", "9S-01", "9S-03"]
    still, missing, blank, other = (e.note for e in result.evidence)
    assert "still marked suggested" in still
    assert "no outcome for them" in missing
    assert "showed no result" in blank
    assert (
        '"You kept going." where the teacher confirmed "You set out your working clearly."' in other
    )
    assert_plain(result)


def test_c9_did_not_come_up():
    data = run(outcomes=[outcome_of("9S-01", status="confirmed", confirmed=NOTE_FOR_1)])
    assert c9(data).outcome == "did not come up"
    # Confirmed, and no pupil's page was read afterwards.
    data = run(
        outcomes=[outcome_of("9S-01", status="confirmed", confirmed=NOTE_FOR_1)],
        events=[confirmed("9S-01")],
    )
    result = c9(data)
    assert result.outcome == "did not come up"
    assert "No pupil's page was read" in result.detail


# ---------- C10: an attached text reaches the tutor ----------

WITH_TEXTS = [
    lesson("c-english", "S5", "English", age=12, drafted=DRAFTED),
    lesson("b-history", "S7", "history", age=16, drafted=DRAFTED),
    lesson("a-maths", "S6", age=13, drafted=DRAFTED),
]


def test_c10_passes_on_a_good_run():
    data = run(
        lessons=WITH_TEXTS,
        turns=[
            turn("7C-01", session="S5", manifest={"material_ids": ["M1"]}),
            turn("11B-01", session="S7", manifest={"material_ids": ["M2"]}),
            turn("11B-02", session="S7", outcome="withheld", manifest={"material_ids": ["M2"]}),
            # A lesson with no text attached.
            turn("8A-01", session="S6"),
        ],
    )
    result = c10(data)
    assert result.outcome == "pass"
    assert "the poem lesson: 1 of 1 reply" in result.detail
    assert "the history lesson: 2 of 2 replies" in result.detail


def test_c10_fails_on_a_bad_run():
    data = run(
        lessons=WITH_TEXTS,
        turns=[
            turn("7C-01", session="S5", said="like a cloud", manifest={"material_ids": []}),
            turn("11B-01", session="S7", manifest={"material_ids": ["M2"]}),
        ],
    )
    result = c10(data)
    assert result.outcome == "fail"
    assert [(e.pupil, e.lesson, e.said) for e in result.evidence] == [
        ("7C-01", "c-english", "like a cloud")
    ]
    assert "without the text" in result.evidence[0].note
    assert_plain(result)


def test_c10_did_not_come_up():
    # Both lessons set up from an earlier run's briefs, so no text was attached this time.
    data = run(
        lessons=[
            lesson("c-english", "S5", "English", age=12),
            lesson("b-history", "S7", "history", age=16),
        ],
        turns=[turn("7C-01", session="S5")],
    )
    assert c10(data).outcome == "did not come up"
    # Drafted and run, with no reply from the tutor in it.
    data = run(lessons=WITH_TEXTS, turns=[turn("8A-01", session="S6")])
    assert c10(data).outcome == "did not come up"


# ---------- C11: a follow-up lesson drafts when taken up ----------


def follow_up(
    drafted: bool = True, lesson_id: str | None = "lesson-9", reason: str = "", **more
) -> dict:
    return event(
        "follow up",
        session_id="S1",
        text="checking an answer by putting it back in",
        drafted=drafted,
        lesson_id=lesson_id,
        reason=reason,
        **more,
    )


def test_c11_passes_on_a_good_run():
    result = c11(run(events=[follow_up()]))
    assert result.outcome == "pass" and result.detail.endswith("1 of 1.")


def test_c11_fails_on_a_bad_run():
    data = run(
        events=[
            follow_up(),
            follow_up(False, None, "The class agent did not draft the lesson."),
            follow_up(False, None, status=503),
            # Said to have drafted, with no lesson to show for it.
            follow_up(True, None),
        ]
    )
    result = c11(data)
    assert result.outcome == "fail"
    assert len(result.evidence) == 3
    assert "The class agent did not draft the lesson." in result.evidence[0].note
    assert "503" in result.evidence[1].note
    assert all("no draft lesson came of it" in e.note for e in result.evidence)
    assert_plain(result)


def test_c11_did_not_come_up():
    result = c11(run())
    assert result.outcome == "did not come up" and "offered" in result.detail


# ---------- U1: help buttons help and are not a try ----------


def test_u1_passes_on_a_good_run():
    wrong, wrong_turn = replied("9S-05", "wrong", "x = 7", tries=1)
    why, why_turn = replied("9S-05", "button:why_wrong", tries=1)
    # Held back, which still counts as a reply.
    other, other_turn = replied(
        "9S-06", "button:another_way", outcome="withheld", reply_text=HELD_BACK
    )
    data = run(
        turns=[wrong_turn, why_turn, other_turn],
        sent=[
            sent("9S-05", "open", line="L0"),
            wrong,
            # Another pupil's request, between this pupil's two.
            sent("9S-06", "wrong", "x = 9", line="L8", tries=3),
            why,
            other,
            # Refused once the lesson had closed.
            sent("9S-07", "button:example", status=409),
        ],
    )
    result = u1(data)
    assert result.outcome == "pass"
    assert result.detail == (
        "3 presses of a help button sent, 2 tied to a reply; 0 presses counted as a wrong try."
    )


def test_u1_counts_wrong_tries_on_the_step_they_were_made_on():
    # The press's page is on another step, which had a wrong try from before: not this press's.
    left, left_turn = replied("9S-05", "wrong", "x = 7", step=0, tries=0)
    press, press_turn = replied("9S-05", "button:example", step=1, tries=1)
    assert u1(run(turns=[left_turn, press_turn], sent=[left, press])).outcome == "pass"


def test_u1_fails_on_a_bad_run():
    wrong, wrong_turn = replied("9S-05", "wrong", "x = 7", tries=1)
    why, why_turn = replied("9S-05", "button:why_wrong", tries=2)
    # Answered with the tutor's line from before: no reply to it.
    again = sent("9S-05", "button:another_way", line=wrong.agent_line_id, tries=2)
    result = u1(run(turns=[wrong_turn, why_turn], sent=[wrong, why, again]))
    assert result.outcome == "fail"
    tried, unanswered = result.evidence
    assert (tried.pupil, tried.said, tried.reply) == (
        "9S-05",
        INTENTS["why_wrong"],
        why_turn.reply_text,
    )
    assert "counted as a wrong try (1 before it, 2 after)" in tried.note
    assert (unanswered.said, unanswered.reply) == (INTENTS["another_way"], "")
    assert "got no reply from the tutor" in unanswered.note
    assert_plain(result)


def test_u1_did_not_come_up():
    result = u1(run(sent=[sent("9S-07", "button:example", status=409)]))
    assert result.outcome == "did not come up"
    assert "1 press of a help button sent, 0 tied to a reply" in result.detail


# ---------- U2: an it helped tap is kept ----------


def test_u2_passes_on_a_good_run():
    said, answer = replied("9S-06", "right", "x = 5", helped=True)
    # The page that came back with the tap already shows the tutor's answer to the teacher's
    # guidance; the tap went on the reply that was on screen.
    guided_turn = turn("9S-06", line="LG", request={"text": None, "guidance": HINT})
    data = run(turns=[answer, guided_turn], sent=[said, sent("9S-06", "helped", line="LG")])
    result = u2(data)
    assert result.outcome == "pass" and result.detail.endswith("1 of 1.")


def test_u2_fails_on_a_bad_run():
    said, answer = replied("9S-06", "right", "x = 5")
    other, other_answer = replied("9S-07", "wrong", "x = 7", helped=False)
    data = run(
        turns=[answer, other_answer],
        sent=[
            said,
            sent("9S-06", "helped", line=said.agent_line_id),
            other,
            sent("9S-07", "helped", line=other.agent_line_id),
        ],
    )
    result = u2(data)
    assert result.outcome == "fail"
    assert [(e.pupil, e.said, e.reply) for e in result.evidence] == [
        ("9S-06", "x = 5", answer.reply_text),
        ("9S-07", "x = 7", other_answer.reply_text),
    ]
    assert "not kept with it" in result.evidence[0].note
    assert_plain(result)


def test_u2_leaves_out_a_tap_on_a_line_no_reply_wrote():
    said, answer = replied("9S-06", "right", "x = 5", helped=True)
    data = run(
        turns=[answer],
        sent=[
            said,
            sent("9S-06", "helped", line=said.agent_line_id),
            sent("9S-07", "open", line="L-unknown"),
            sent("9S-07", "helped", line="L-unknown"),
        ],
    )
    result = u2(data)
    assert result.outcome == "pass"
    assert result.detail.endswith(
        "1 of 1. Left out: 1 tap on a line no reply of the tutor's wrote."
    )
    # With only such a tap, nothing is left to judge, and the detail says the tap went through.
    data = run(sent=[sent("9S-07", "open", line="L9"), sent("9S-07", "helped", line="L9")])
    result = u2(data)
    assert result.outcome == "did not come up"
    assert result.detail == (
        "1 tap saying a reply helped went through, on a line no reply of the tutor's wrote, so "
        "none could be checked."
    )


def test_u2_did_not_come_up():
    result = u2(run(sent=[sent("9S-06", "helped", status=409)]))
    assert result.outcome == "did not come up"
    assert result.detail == "No pupil's tap saying a reply helped went through."


# ---------- U3: a late pupil starts at the beginning ----------

LATE = {
    "9S-28": who(joins_after_s=180),
    "9S-29": who(joins_after_s=180),
    "9S-30": who(joins_after_s=180),
    "9S-01": who("strong"),
}


def test_u3_passes_on_a_good_run():
    data = run(
        cast=LATE,
        sent=[
            # A pupil there from the start, a few steps in: not U3's business.
            sent("9S-01", "right", "x = 5", line="L1", step=2),
            sent("9S-29", "open", line="L2", step=0),
            sent("9S-30", "open", line="L3", step=0),
        ],
    )
    result = u3(data)
    assert result.outcome == "pass" and result.detail.endswith("2 of 2.")


def test_u3_fails_on_a_bad_run():
    data = run(
        cast=LATE,
        sent=[
            sent("9S-28", "open", line="L2", step=2),
            sent("9S-29", "open", line=None, step=0),
            sent("9S-30", "open", status=500),
        ],
    )
    result = u3(data)
    assert result.outcome == "fail"
    started, blank, failed = result.evidence
    assert started.pupil == "9S-28" and "they started at step 3" in started.note
    assert "no opening from the tutor" in blank.note
    assert "the lesson did not open for them (the platform answered 500)" in failed.note
    assert_plain(result)


def test_u3_did_not_come_up():
    assert u3(run(cast={"9S-01": who()})).outcome == "did not come up"
    # Joined once the lesson had closed.
    result = u3(run(cast=LATE, sent=[sent("9S-29", "open", status=409)]))
    assert result.outcome == "did not come up"


# ---------- U4: signing back in returns to the same place ----------


def test_u4_passes_on_a_good_run():
    data = run(
        sent=[
            sent("9S-15", "open", line="L0", step=0, lines=1),
            sent("9S-15", "right", "x = 5", line="L1", step=1, lines=4),
            # Another pupil's page, on another step, between the two.
            sent("9S-16", "right", "x = 5", line="L2", step=3, lines=9),
            # Back with one line more: Ask my teacher's note, written while they were away.
            sent("9S-15", "signed_back_in", line="L1", step=1, lines=5),
        ]
    )
    result = u4(data)
    assert result.outcome == "pass" and result.detail.endswith("1 of 1.")


def test_u4_fails_on_a_bad_run():
    data = run(
        sent=[
            sent("9S-15", "right", "x = 5", line="L1", step=1, lines=4),
            sent("9S-15", "signed_back_in", line="L1", step=0, lines=4),
            sent("9S-16", "right", "x = 5", line="L2", step=1, lines=6),
            sent("9S-16", "signed_back_in", line="L2", step=1, lines=2),
            sent("9S-17", "right", "x = 5", line="L3", step=1, lines=6),
            sent("9S-17", "signed_back_in", status=401),
        ]
    )
    result = u4(data)
    assert result.outcome == "fail"
    step, lines, refused = result.evidence
    assert step.pupil == "9S-15" and "they came back to step 1, not step 2" in step.note
    assert "their page showed 2 lines, not the 6 it had" in lines.note
    assert "could not read their page (the platform answered 401)" in refused.note
    assert_plain(result)


def test_u4_did_not_come_up():
    assert u4(run(sent=[sent("9S-15", "right", "x = 5", line="L1")])).outcome == "did not come up"
    data = run(
        sent=[
            sent("9S-15", "right", "x = 5", line="L1"),
            sent("9S-15", "signed_back_in", status=409),
        ]
    )
    assert u4(data).outcome == "did not come up"
    # Signed back in with no page of theirs from before to hold it to.
    assert u4(run(sent=[sent("9S-15", "signed_back_in", line="L1")])).outcome == "did not come up"


# ---------- S1: no errors, and every message got a reply ----------


def test_s1_passes_on_a_good_run():
    wrote, answer = replied("9S-01", "right", "x = 5")
    held, held_back = replied(
        "9S-02", "ask_answer", "just tell me", outcome="withheld", reply_text=HELD_BACK
    )
    pressed, help_turn = replied("9S-03", "button:example")
    tapped, tap_turn = replied("9S-04", "double_tap", "is it 10")
    data = run(
        turns=[answer, held_back, help_turn, tap_turn],
        sent=[
            sent("9S-01", "open", line="L0"),
            wrote,
            held,
            pressed,
            # A double tap: one tap answered, the other held back as it should be.
            sent("9S-04", "double_tap", "is it 10", status=429),
            tapped,
            # Not messages: their answer shows the tutor's line from before.
            sent("9S-01", "helped", line=wrote.agent_line_id),
            sent("9S-01", "ask_teacher", line=wrote.agent_line_id),
            # Refused once the lesson had closed: not a problem.
            sent("9S-05", "right", "x = 5", status=409),
        ],
        events=[
            {"what": "rate limited", "pupil": "9S-04", "beat": "right", "at": at(5), "detail": ""},
            {"what": "rate limited", "pupil": "9S-04", "beat": "right", "at": at(10), "detail": ""},
            {"what": "unavailable", "pupil": "9S-02", "beat": "right", "at": at(15), "detail": ""},
        ],
    )
    result = s1(data)
    assert result.outcome == "pass"
    assert result.detail.startswith("Messages answered: 4, of which 4 got a reply.")
    assert "2 times a reply was still on its way" in result.detail
    assert "1 time the tutor was not available" in result.detail


def test_s1_takes_a_double_tap_both_answered_as_one_message():
    # Both taps answered, and both pages show the newer of the two replies.
    first_turn = turn("9S-04", said="is it 10")
    second_turn = turn("9S-04", said="is it 10")
    data = run(
        turns=[first_turn, second_turn],
        sent=[
            sent("9S-04", "double_tap", "is it 10", line=second_turn.agent_line_id),
            sent("9S-04", "double_tap", "is it 10", line=second_turn.agent_line_id),
        ],
    )
    result = s1(data)
    assert result.outcome == "pass"
    assert result.detail.startswith("Messages answered: 1, of which 1 got a reply.")


def test_s1_fails_on_a_bad_run():
    wrote, answer = replied("9S-01", "right", "x = 5")
    data = run(
        cast={"9S-01": who(), "9S-02": who()},
        turns=[answer],
        sent=[
            wrote,
            # Answered, with the reply from before on the page: no reply to it.
            sent("9S-01", "wrong", "x = 7", line=wrote.agent_line_id),
            sent("9S-02", "right", "x = 5", status=502),
            # A double tap whose one answered tap shows the reply from before: no reply to it.
            sent("9S-02", "double_tap", "is it 10", line=wrote.agent_line_id),
        ],
        errors=["9S-02, right: 502 Bad Gateway", "teacher: stopped by a failed request"],
    )
    result = s1(data)
    assert result.outcome == "fail"
    assert [(e.pupil, e.said) for e in result.evidence] == [
        ("9S-02", ""),
        ("", ""),
        ("9S-02", "x = 5"),
        ("9S-01", "x = 7"),
        ("9S-02", "is it 10"),
    ]
    assert result.evidence[0].note == "The run's log says: 9S-02, right: 502 Bad Gateway"
    assert result.evidence[2].note == "The platform answered 502."
    assert "no new line from the tutor" in result.evidence[3].note
    assert "Problems in the run's log: 2." in result.detail
    assert "Answers that were the platform failing: 1." in result.detail
    assert_plain(result)


def test_s1_did_not_come_up():
    assert s1(run()).outcome == "did not come up"
    # Only openings: nothing went wrong, but no message was answered to show a reply.
    openings = run(sent=[sent("9S-01", "open", line="L0"), sent("9S-02", "open", line="L1")])
    result = s1(openings)
    assert result.outcome == "did not come up"
    assert result.detail.startswith("No message a pupil sent was answered.")
    assert "Problems in the run's log: 0." in result.detail
    # A problem in the log fails it even so.
    openings.errors.append("9S-01, open: 500 Internal Server Error")
    assert s1(openings).outcome == "fail"


# ---------- S2: replies come quickly enough ----------


def waits(session: str, seconds: list[float], beat: str = "right") -> list[Sent]:
    return [sent("p", beat, "x", line=f"L{_next()}", session=session, seconds=s) for s in seconds]


def test_s2_passes_on_a_good_run():
    data = run(
        lessons=TWO_LESSONS,
        sent=[
            # Part 1: 19 in 20 within exactly 30 seconds, which passes.
            *waits("S1", [3.0] * 18 + [30.0, 31.0]),
            # Part 2: half within exactly 10 seconds, which passes, the opening among them.
            *waits("S2", [10.0, 10.0, 2.0, 12.0]),
            sent("8A-01", "open", line="LO", session="S2", seconds=10.0),
            # Not a reply from the tutor, or not answered.
            sent("9S-01", "helped", line="LX", seconds=40.0),
            sent("9S-01", "signed_back_in", line="LX", seconds=40.0),
            sent("9S-01", "ask_teacher", line="LX", seconds=40.0),
            sent("9S-01", "right", "x", status=429, seconds=40.0),
        ],
    )
    result = s2(data)
    assert result.outcome == "pass"
    assert (
        "Part 1: 20 replies, half within 3.0 seconds and 19 in 20 within 30.0 seconds."
        in result.detail
    )
    assert (
        "Part 2: 5 replies, half within 10.0 seconds and 19 in 20 within 12.0 seconds."
        in result.detail
    )


def test_s2_fails_on_a_bad_run():
    data = run(
        lessons=[lesson(), lesson("b-history", "S2", "history", age=16)],
        # Part 1: half too slow. Part 2: the slowest 1 in 20 too slow.
        sent=[*waits("S1", [11.0, 12.0, 9.0]), *waits("S2", [2.0] * 9 + [31.0])],
    )
    result = s2(data)
    assert result.outcome == "fail"
    assert [e.note for e in result.evidence] == [
        "This reply took 12.0 seconds (Part 1).",
        "This reply took 11.0 seconds (Part 1).",
        "This reply took 31.0 seconds (Part 2).",
    ]
    assert_plain(result)


def test_s2_judges_a_part_that_ran_on_its_own():
    result = s2(run(sent=waits("S1", [3.0, 4.0])))
    assert result.outcome == "pass" and "Part 2: no replies." in result.detail
    result = s2(run(sent=[sent("8A-01", "open", line="L1", session="S9", seconds=45.0)]))
    assert result.outcome == "fail"
    assert result.evidence[0].note == "The tutor's opening took 45.0 seconds (Part 2)."


def test_s2_shows_a_slow_reply_with_what_the_pupil_said_and_the_tutor_replied():
    slow, slow_turn = replied("9S-01", "not_sure", "not sure tbh", seconds=42.0)
    (shown,) = s2(run(turns=[slow_turn], sent=[slow])).evidence
    assert (shown.pupil, shown.lesson, shown.said, shown.reply) == (
        "9S-01",
        FULL_CLASS,
        "not sure tbh",
        slow_turn.reply_text,
    )
    assert shown.note == "This reply took 42.0 seconds (Part 1)."


def test_s2_did_not_come_up():
    assert s2(run(sent=[sent("9S-01", "right", "x", status=429)])).outcome == "did not come up"


# ---------- S3: the class view loads quickly ----------


def test_s3_passes_on_a_good_run():
    result = s3(run(view_seconds=[0.4, 2.9, 3.0]))
    assert result.outcome == "pass"
    assert "loaded 3 times; the slowest took 3.0 seconds" in result.detail


def test_s3_fails_on_a_bad_run():
    result = s3(run(view_seconds=[0.4, 3.4, 5.0]))
    assert result.outcome == "fail"
    assert [e.note for e in result.evidence] == [
        "One load of the class view took 5.0 seconds.",
        "One load of the class view took 3.4 seconds.",
    ]
    assert {e.lesson for e in result.evidence} == {FULL_CLASS}
    assert_plain(result)


def test_s3_did_not_come_up():
    assert s3(run(view_seconds=[])).outcome == "did not come up"
    # The 30-pupil lesson did not run, or never started: other class views are not its.
    for lessons in ([lesson("a-maths", "S2", age=13)], [lesson(FULL_CLASS, "")]):
        result = s3(run(lessons=lessons, view_seconds=[9.0]))
        assert result.outcome == "did not come up"
        assert result.detail == "The 30-pupil lesson did not run."


# ---------- S4: nobody noticed ----------


def test_s4_passes_on_a_good_run():
    wrote, answer = replied(
        "9S-01",
        "right",
        "x = 5",
        reply_text="Spot on. Now the bottom row, and good luck with your test on Friday.",
    )
    data = run(
        turns=[
            answer,
            turn("9S-02", reply_text="Said like a pro: aim for the main idea."),
            # Group B's science and the full class's maths can say these and notice nothing.
            turn("11B-03", reply_text="Greenhouses use artificial light in winter."),
            turn("9S-05", reply_text="Half a person is not a real number of people here."),
            # The tutor saying what it is, to a pupil chatting about football, is not noticing
            # anything about the pupil.
            turn("9S-06", reply_text=FOOTBALL),
        ],
        sent=[
            wrote,
            # Fixed texts, not the pupil's own words: one is far longer than a pupil types.
            sent("9S-02", "long_paste", CANNED["long_paste"], line="L7"),
            sent("9S-03", "greek", CANNED["greek"], line="L8"),
            # Copied word for word from another pupil, whose words are checked as theirs.
            sent("9S-04", "copied_wrong", "is it 10!", line="L9"),
        ],
        teacher_replies=[
            "9S-22 is upset about a test on Friday.",
            "The AI tutor answered every one of them.",
        ],
        events=[event("asked", session_id="S1", question="Who needs me?", reply="Nobody else.")],
    )
    result = s4(data)
    assert result.outcome == "pass"
    assert "5 from the tutor and 3 from the class agent; 0 say" in result.detail
    assert "Pupil messages checked: 1; 0 do not read" in result.detail


FOOTBALL = "I don't watch matches, being an AI, but a last minute winner sounds amazing."


@pytest.mark.parametrize(
    ("words", "noticed"),
    [
        ("Greenhouses use artificial light in winter.", None),
        ("-1 is not a real number of apples.", None),
        ("Said it well, and aim for the bottom line.", None),
        # The tutor describing itself is not treating the pupil as anything.
        (FOOTBALL, None),
        ("As an AI, I can't text you, but your teacher can help.", None),
        ("Is the AI tutor fine?", None),
        ("These look simulated.", None),
        ("Are you really sure? Check the bottom line.", None),
        # Calling the pupil a bot, an AI or part of a test is noticing.
        ("are you a bot?", "are you a bot"),
        ("You're an AI, aren't you", "You're an AI"),
        (f"you{chr(0x2019)}re just a robot lol", f"you{chr(0x2019)}re just a robot"),
        ("You are a chatbot.", "You are a chatbot"),
        ("Aren't you a program?", "Aren't you a program"),
        ("Are you even real? Are you real?", "Are you real"),
        ("Is artificial intelligence writing these?", "artificial intelligence writing these"),
        # Quoted on one line in the note.
        ("Is Artificial\nIntelligence writing these?", "Artificial Intelligence writing these"),
        ("This is not a real pupil.", "not a real pupil"),
        ("Not a real person, surely.", "Not a real person"),
        ("It is not a real student.", "not a real student"),
        ("That is not a real child.", "not a real child"),
        ("A test pupil, maybe.", "test pupil"),
        ("Two simulated pupils joined.", "simulated pupils"),
        ("This was written by AI.", "written by AI"),
    ],
)
def test_s4_finds_only_the_words_that_give_the_game_away(words, noticed):
    result = s4(run(turns=[turn("9S-01", reply_text=words)]))
    if noticed is None:
        assert result.evidence == []
    else:
        assert [e.note for e in result.evidence] == [f'The tutor\'s reply says "{noticed}".']


def test_s4_fails_on_a_bad_run():
    wrote, answer = replied("9S-01", "right", "x = 5", reply_text="Are you a bot? You answer fast.")
    data = run(
        turns=[answer, turn("9S-02", reply_text="This looks like a Test  Pupil account.")],
        sent=[
            wrote,
            sent("9S-03", "not_sure", "as an ai im not sure", line="L5"),
            sent("9S-04", "double_tap", "is it 10\nor 12", status=429),
        ],
        teacher_replies=[
            "Some of these could be simulated pupils.",
            # The class agent naming the tutor for what it is notices nothing about a pupil.
            "The ai tutor is fine.",
            "Could artificial  intelligence be writing these?",
        ],
        events=[
            event(
                "asked",
                session_id="S1",
                question="Who needs me right now?",
                reply="9S-05 is not a real\npupil, I think.",
            )
        ],
    )
    result = s4(data)
    assert result.outcome == "fail"
    notes = [e.note for e in result.evidence]
    assert notes[0] == """The tutor's reply says "Are you a bot"."""
    assert notes[1] == """The tutor's reply says "Test Pupil"."""
    assert notes[2].startswith(
        """The class agent's reply to the teacher says "simulated pupils":"""
    )
    assert notes[3] == (
        "The class agent's reply to the teacher says \"artificial intelligence be writing "
        'these": "Could artificial intelligence be writing these?"'
    )
    assert notes[4] == (
        'The class agent\'s reply to the teacher says "not a real pupil": '
        '"9S-05 is not a real pupil, I think."'
    )
    assert result.evidence[4].lesson == FULL_CLASS
    assert "2 from the tutor and 4 from the class agent; 5 say" in result.detail
    assert [(e.pupil, e.said) for e in result.evidence[5:]] == [
        ("9S-03", "as an ai im not sure"),
        ("9S-04", "is it 10\nor 12"),
    ]
    assert "does not read as a pupil's" in notes[5]


def test_s4_needs_both_halves_to_pass():
    """Replies to read, and pupils' own words to read: with either missing it did not come up,
    and a fail in either fails."""
    replies_only = run(turns=[turn("9S-01", reply_text="Good, now try the next one.")])
    result = s4(replies_only)
    assert result.outcome == "did not come up"
    assert "No message a pupil wrote to check." in result.detail
    words_only = run(sent=[sent("9S-01", "right", "x = 5", line="L1")])
    result = s4(words_only)
    assert result.outcome == "did not come up"
    assert "No reply from the tutor or the class agent to check." in result.detail
    odd_only = run(sent=[sent("9S-01", "right", "as an ai, x = 5", line="L1")])
    assert s4(odd_only).outcome == "fail"


def test_s4_did_not_come_up():
    assert s4(run()).outcome == "did not come up"


def test_s4_reads_what_the_review_wrote_about_each_pupil():
    """The lines an end of lesson review wrote on how a pupil learns are the agent writing about
    them too: one that calls them a bot fails S4. The tutor's counted lines are not the agent's
    words about the pupil, so they are not read."""

    def line(sentence: str, source: str = "review") -> dict:
        return {
            "sentence": sentence,
            "at": "2026-11-22T10:00:00+00:00",
            "source": source,
            "category": "how",
            "session_id": "S1",
        }

    wrote = sent("9S-01", "right", "x = 5", line="L1")
    data = run(sent=[wrote], turns=[turn("9S-02", reply_text="Good, now the next one.")])
    data.note_lines = {
        "9S-01": [line("Answers like a bot, the same short way every time.")],
        "9S-02": [line("Says more when asked to explain."), line("Bot-like counts.", "counted")],
    }
    result = s4(data)
    assert result.outcome == "fail"
    [noticed] = [e for e in result.evidence if e.pupil == "9S-01"]
    assert noticed.lesson == FULL_CLASS
    assert noticed.note == (
        'A line the end of lesson review wrote about this pupil says "bot": '
        '"Answers like a bot, the same short way every time."'
    )
    assert "Lines the end of lesson review wrote about pupils: 2; 1 call the pupil" in result.detail
    # Review lines alone are something to read: with the pupils' words, S4 can pass on them.
    data.note_lines = {"9S-01": [line("Says more when asked to explain.")]}
    data.turns = []
    assert s4(data).outcome == "pass"


# ---------- what the runner may log oddly ----------


def test_the_checks_do_not_stumble_on_what_they_cannot_read():
    """A time or a day the runner logged that cannot be read is left out, never a crash."""
    # A note kept with no readable day, and nobody asked about it: nothing to judge.
    unreadable = note("someday", "not a time")
    data = run(lessons=[same_questions(False, drafted=None)], cast=GROUP_A, notes=[unreadable])
    assert c2(data).outcome == "did not come up"
    # Asked for, and kept with no readable last day: it fails, saying so.
    data = run(lessons=[same_questions(False)], cast=GROUP_A, events=[gently()], notes=[unreadable])
    result = c2(data)
    assert result.outcome == "fail" and "kept with no last day" in result.evidence[0].note
    # A pause logged with no time it held from.
    paused, resumed = pause_and_resume()
    paused["done"] = paused["at"] = None
    assert c8(run(events=[paused, resumed])).outcome == "did not come up"
    # Times written with no zone are taken as UTC, as the driver's own are.
    paused, resumed = pause_and_resume()
    paused.update(at="2026-11-21T09:05:00", done="2026-11-21T09:05:01")
    resumed.update(at="2026-11-21T09:06:00", done="2026-11-21T09:06:01")
    data = run(
        sent=[sent("9S-01", "open", line="L0", when=10)],
        events=[
            paused,
            resumed,
            turned_away("9S-01", 310),
            extended("2026-11-21T09:40:00", "2026-11-21T09:50:00"),
        ],
    )
    result = c8(data)
    assert "pupils were turned away 1 time" in result.detail
    assert "as far as it should: 1 of 1" in result.detail
    # An outcome marked confirmed with no note to compare with what the page shows.
    data = run(
        outcomes=[outcome_of("9S-01", status="confirmed")],
        events=[confirmed("9S-01"), seen("9S-01", on_page(NOTE_FOR_2))],
    )
    assert c9(data).outcome == "pass"


def test_a_409_fails_an_action_unless_it_means_the_lesson_had_ended():
    """Only for guidance, a pause, a resume and extra minutes does a 409 mean the lesson had
    already ended, so that the action never happened and is left out (their own tests show it).
    For every other action it is the platform refusing, and the check fails, saying so."""
    asked = run(cast=CLASS, sent=needs(), events=[who_needs_me("", status=409)])
    result = c5(asked)
    assert result.outcome == "fail" and "The platform answered 409." in result.evidence[0].note
    assert c11(run(events=[follow_up(False, None, status=409)])).outcome == "fail"
    kept_none = run(lessons=[same_questions(False)], cast=GROUP_A, events=[gently(status=409)])
    assert c2(kept_none).outcome == "fail"
    still_open = run(alerts=[alert(UPSET, aid="A1")], events=[dealt_with("A1", status=409)])
    assert c6(still_open).outcome == "fail"
    assert c7(run(events=[read("9S-04", status=409)])).outcome == "fail"
    not_marked = run(outcomes=[outcome_of("9S-01")], events=[confirmed("9S-01", status=409)])
    assert c9(not_marked).outcome == "fail"
    summed_up = event("summary", session_id="S1", status=409)
    no_outcome = run(sent=[sent("9S-01", "right", "x = 5", line="L1")], events=[summed_up])
    assert c4(no_outcome).outcome == "fail"
