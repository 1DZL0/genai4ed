"""What a lesson keeps about its activity: the heading, the exact kind, and the server's own
record of what the teacher pressed and what they did with the agent's guess.

The heading and the kind are written by the agent. The record is written by the server only:
it is not in the reply shape the model is given, and a model that sends one is ignored.
"""

import pytest
from pydantic import ValidationError

from app.agent import lessons
from app.agent.brief import ActivityRecord, LessonBrief
from app.agent.llm import FRESH, ScriptedClient, bare_schema, get_llm_client
from app.agent.policy import PANEL_PREFIX
from app.agent.thread import SYSTEM
from app.enums import ActivityKind
from app.models import LessonContract
from tests.lessons import THREE
from tests.test_moving_between_steps import OPEN, script, start
from tests.test_thread import last_card, say

OLD = THREE.model_dump(mode="json")
for _new in ("heading", "activity_kind", "listed_kind", "record"):
    OLD.pop(_new, None)
for _step in OLD["steps"]:
    for _new in ("heading", "activity_kind", "listed_kind"):
        _step.pop(_new, None)


def _with(**changes) -> dict:
    return {**OLD, **changes}


def test_a_lesson_made_before_this_opens_with_no_heading_and_reads_as_before():
    brief = LessonBrief.model_validate(OLD)
    assert (brief.heading, brief.activity_kind, brief.listed_kind) == ("", "", "")
    assert brief.record == ActivityRecord()
    assert (brief.heading_from, brief.kind_from) == ("", "")
    assert brief.missing() == THREE.missing() == []
    assert brief.as_text() == THREE.as_text()
    assert [(s.heading, s.activity_kind, s.listed_kind) for s in brief.steps] == [("", "", "")] * 3


def test_the_heading_the_kind_and_the_record_survive_being_stored_and_read_back():
    record = {"picked": ["maths"], "picked_when": "before", "guess": "standing"}
    brief = LessonBrief.model_validate(
        _with(
            heading="maths",
            activity_kind="multi-step equations, each step explained",
            listed_kind="multi-step problems",
            record=record,
        )
    )
    again = LessonBrief.model_validate(brief.model_dump(mode="json"))
    assert again == brief
    assert (again.heading, again.listed_kind) == ("maths", "multi-step problems")
    assert again.record.picked == ["maths"]
    assert (again.record.picked_when, again.record.guess) == ("before", "standing")


def test_a_heading_is_kept_as_its_key_however_the_agent_writes_it():
    assert LessonBrief.model_validate(_with(heading="Mathematics tasks")).heading == "maths"
    assert LessonBrief.model_validate(_with(heading=" READING ")).heading == "reading"
    # A heading that is none of the seven is "Something else", never an eighth heading.
    assert LessonBrief.model_validate(_with(heading="a debate")).heading == "other"
    assert LessonBrief.model_validate(_with(heading=None)).heading == ""


def test_a_kind_on_the_list_is_kept_in_the_lists_own_words():
    said = LessonBrief.model_validate(
        _with(
            activity_kind="a find-the-mistake task",
            listed_kind="Error Identification and Correction",
        )
    )
    assert said.listed_kind == "error identification and correction"
    # The agent's own words for it are left as it said them.
    assert said.activity_kind == "a find-the-mistake task"
    # Naming the kind by the list's name is enough to put it on the list.
    named = LessonBrief.model_validate(_with(activity_kind="Summary writing"))
    assert named.listed_kind == "summary writing"


def test_a_kind_that_is_not_on_the_list_is_recorded_as_the_agents_own_words():
    brief = LessonBrief.model_validate(
        _with(heading="other", activity_kind="a debate in pairs", listed_kind="debating")
    )
    assert brief.listed_kind == ""
    assert brief.kind_from == "own_words"


def test_where_the_heading_came_from_follows_what_the_teacher_pressed():
    worked_out = LessonBrief.model_validate(_with(heading="writing"))
    assert worked_out.heading_from == "worked_out"
    before = LessonBrief.model_validate(
        _with(heading="writing", record={"picked": ["writing"], "picked_when": "before"})
    )
    assert before.heading_from == "picked_before"
    asked = LessonBrief.model_validate(
        _with(heading="writing", record={"picked": ["writing"], "picked_when": "asked"})
    )
    assert asked.heading_from == "picked_in_chat"
    # The teacher pressed Writing and the agent read the words as a quiz: the heading on the
    # lesson is the agent's, and the pick is still on the record.
    other = LessonBrief.model_validate(
        _with(heading="choice", record={"picked": ["writing"], "picked_when": "before"})
    )
    assert other.heading_from == "worked_out"
    assert other.record.picked == ["writing"]


def test_where_the_kind_came_from_is_the_list_the_agents_words_or_the_teachers_correction():
    listed = LessonBrief.model_validate(_with(activity_kind="x", listed_kind="multiple choice"))
    assert listed.kind_from == "list"
    corrected = LessonBrief.model_validate(
        _with(
            activity_kind="finding the mistakes in worked answers",
            listed_kind="error identification and correction",
            record={"guess": "corrected", "correction": "no, find the mistakes"},
        )
    )
    assert corrected.kind_from == "teacher"
    assert corrected.record.correction == "no, find the mistakes"


def test_a_step_keeps_its_own_heading_and_kind_only_when_they_differ_from_the_lessons():
    steps = [dict(s) for s in OLD["steps"]]
    steps[2] = {
        **steps[2],
        "heading": "Writing tasks",
        "activity_kind": "a paragraph explaining the method",
        "listed_kind": "PARAGRAPH WRITING",
    }
    brief = LessonBrief.model_validate(
        _with(
            heading="maths",
            activity_kind="equations",
            listed_kind="multi-step problems",
            steps=steps,
        )
    )
    assert brief.heading_of(0) == "maths"
    assert brief.kind_of(0) == ("equations", "multi-step problems")
    assert brief.heading_of(2) == "writing"
    assert brief.kind_of(2) == ("a paragraph explaining the method", "paragraph writing")
    assert brief.headings() == ["maths", "writing"]
    # A step number that is not in the lesson has the lesson's.
    assert brief.heading_of(9) == "maths"


def test_the_reply_shape_the_agent_is_given_has_the_heading_and_the_kind_and_no_record():
    schema = bare_schema(LessonBrief.model_json_schema())
    fields = schema["properties"]
    assert {"heading", "activity_kind", "listed_kind"} <= set(fields)
    assert "record" not in fields
    assert "ActivityRecord" not in schema.get("$defs", {})
    # The heading is one of the picks by key, or empty until it is known.
    assert fields["heading"]["enum"] == [
        "",
        "writing",
        "maths",
        "open_questions",
        "choice",
        "reading",
        "critical",
        "inquiry",
        "other",
    ]
    step = schema["$defs"]["Step"]["properties"]
    assert {"heading", "activity_kind", "listed_kind"} <= set(step)


def test_a_reply_from_the_model_cannot_write_the_record():
    sent = _with(heading="maths", record={"picked": ["maths"], "guess": "kept_said"})
    fresh = LessonBrief.model_validate(sent, context={FRESH: True})
    assert fresh.record == ActivityRecord()
    # The same brief read back from the database keeps what the server wrote.
    stored = LessonBrief.model_validate(sent)
    assert stored.record.guess == "kept_said"


def test_the_record_takes_only_what_the_server_writes():
    with pytest.raises(ValidationError):
        ActivityRecord(guess="approved by the model")
    with pytest.raises(ValidationError):
        ActivityRecord(picked_when="yesterday")
    with pytest.raises(ValidationError):
        ActivityRecord(picked=["essays"])


def test_the_lesson_shown_to_the_agent_leaves_the_record_out():
    brief = LessonBrief.model_validate(
        _with(heading="maths", record={"picked": ["maths"], "picked_when": "before"})
    )
    shown = brief.for_agent()
    assert '"heading":"maths"' in shown
    assert "record" not in shown
    assert "picked" not in shown


def scripted(app, *replies):
    """Make the agent's next replies exactly these, and hand back what it was shown."""
    agent = ScriptedClient(list(replies))
    app.dependency_overrides[get_llm_client] = lambda: agent
    return agent


def _drafted(**changes) -> dict:
    return {"reply": "Here it is.", "show": "lesson", "brief": _with(**changes)}


async def _stored(db, card) -> tuple[LessonContract, LessonBrief]:
    lesson = await db.get(LessonContract, card["lesson_id"])
    await db.refresh(lesson)
    return lesson, LessonBrief.model_validate(lesson.brief)


async def test_the_agent_is_never_shown_the_record_and_cannot_change_it(app, client, classroom, db):
    agent = scripted(
        app,
        _drafted(heading="maths", activity_kind="equations"),
        _drafted(
            heading="maths",
            activity_kind="equations",
            title="Linear equations two",
            record={"picked": ["writing"], "guess": "kept_said"},
        ),
    )
    card = last_card(await say(client, classroom, "A lesson on linear equations."))
    lesson, brief = await _stored(db, card)
    # What the server wrote when the teacher pressed Mathematics.
    pressed = ActivityRecord(picked=["maths"], picked_when="before", guess="standing")
    brief.record = pressed
    lesson.brief = brief.model_dump(mode="json")
    await db.commit()

    await say(client, classroom, "Call it Linear equations two.")
    shown = agent.calls[-1]["system"]
    assert '"heading":"maths"' in shown
    assert "picked_when" not in shown
    assert '"record"' not in shown
    _, kept = await _stored(db, card)
    assert kept.title == "Linear equations two"
    # Not the reply's "kept_said" or "writing": the server's own step, since the teacher
    # carried on without a word about the guess.
    assert kept.record == pressed.model_copy(update={"guess": "kept_silent"})


async def test_a_change_that_leaves_the_activity_out_keeps_what_the_lesson_had(
    app, client, classroom, db
):
    scripted(
        app,
        _drafted(heading="maths", activity_kind="equations", listed_kind="multi-step problems"),
        _drafted(title="Linear equations two"),
        _drafted(heading="writing"),
    )
    card = last_card(await say(client, classroom, "A lesson on linear equations."))
    await say(client, classroom, "Call it Linear equations two.")
    _, kept = await _stored(db, card)
    assert (kept.heading, kept.activity_kind, kept.listed_kind) == (
        "maths",
        "equations",
        "multi-step problems",
    )
    # A new heading with no kind named: the old kind was a kind of the old heading, and goes.
    await say(client, classroom, "Make it a writing lesson.")
    _, moved = await _stored(db, card)
    assert (moved.heading, moved.activity_kind, moved.listed_kind) == ("writing", "", "")


async def test_a_new_version_of_a_lesson_carries_the_record_with_it(db, classroom):
    brief = LessonBrief.model_validate(
        _with(heading="maths", record={"picked": ["maths"], "picked_when": "before"})
    )
    approved = LessonContract(
        teacher_id=classroom.teacher.id,
        title=brief.title,
        subject=brief.subject,
        status="active",
        brief=brief.model_dump(mode="json"),
    )
    db.add(approved)
    await db.flush()
    draft = await lessons.draft_to_work_on(db, approved)
    assert draft.id != approved.id
    carried = LessonBrief.model_validate(draft.brief)
    assert (carried.heading, carried.record.picked) == ("maths", ["maths"])


async def test_the_tutor_is_not_yet_handed_the_heading_or_the_kind_as_data(db, client, three):
    """The tutor is told the kind in a sentence of its own, written with the tutor's prompt.
    Until then the step it is handed reads exactly as it did."""
    steps = [dict(s) for s in OLD["steps"]]
    steps[0] = {
        **steps[0],
        "heading": "writing",
        "activity_kind": "a paragraph explaining the method",
        "listed_kind": "paragraph writing",
    }
    three.contract.brief = _with(heading="maths", activity_kind="equations", steps=steps)
    await db.commit()
    script(three, OPEN)
    await start(client, three)
    shown = three.tutor.calls[-1]["system"]
    assert '"step_number": 1' in shown or '"step_number":1' in shown
    for field in ("heading", "activity_kind", "listed_kind"):
        assert f'"{field}"' not in shown
    assert "paragraph writing" not in shown


# ---------- the old question: right answers, or open-ended writing ----------


def test_a_lesson_is_no_longer_held_up_for_the_old_question():
    brief = LessonBrief.model_validate(_with(activity=None))
    assert brief.activity is None
    assert brief.missing() == []
    assert not any("right answers" in gap for gap in LessonBrief().missing())


def test_the_shape_of_the_work_comes_from_the_kind_when_it_is_on_the_list():
    # The agent read an essay as right answers: the list knows an essay is judged.
    essay = LessonBrief.model_validate(_with(heading="writing", listed_kind="essay writing"))
    assert essay.activity is ActivityKind.OPEN
    unsaid = LessonBrief.model_validate(
        _with(activity=None, heading="maths", listed_kind="one-step problems")
    )
    assert unsaid.activity is ActivityKind.ANSWERS


def test_a_kind_that_is_not_on_the_list_keeps_the_agents_own_reading_of_its_shape():
    debate = LessonBrief.model_validate(
        _with(activity="open", heading="other", activity_kind="a debate in pairs")
    )
    assert debate.activity is ActivityKind.OPEN
    unsaid = LessonBrief.model_validate(
        _with(activity=None, heading="other", activity_kind="a debate in pairs")
    )
    assert unsaid.activity is None


def test_a_step_with_its_own_kind_has_the_shape_of_that_kind():
    steps = [dict(s) for s in OLD["steps"]]
    steps[2] = {**steps[2], "heading": "writing", "listed_kind": "paragraph writing"}
    brief = LessonBrief.model_validate(
        _with(heading="maths", listed_kind="multi-step problems", steps=steps)
    )
    assert brief.activity_of(0) is ActivityKind.ANSWERS
    assert brief.activity_of(2) is ActivityKind.OPEN


async def test_the_old_settings_sentence_no_longer_sets_the_shape_of_the_work(
    app, client, classroom, db
):
    scripted(app, _drafted(heading="maths", listed_kind="multi-step problems"))
    sent = await client.post(
        "/api/teacher/thread/messages",
        json={
            "text": "A lesson on linear equations.",
            "choices": f"{PANEL_PREFIX} The activity: open-ended writing.",
        },
        headers=classroom.headers(classroom.teacher),
    )
    lesson, _ = await _stored(db, last_card(sent))
    assert lesson.brief["activity"] == "answers"


def test_the_agent_is_not_told_to_ask_the_old_question():
    said = " ".join(SYSTEM.split())
    assert "the kind of activity;" not in said
    assert "Three things every lesson carries" not in said
    # What is asked is the length, the age and, for a bare topic, the kind: never the shape.
    assert "Ask only for what is missing: the length, the age, or the kind of activity" in said
    assert "Everything else you fill in and mark to check" in said
    note = LessonBrief.model_fields["activity"].description
    assert "otherwise asked for" not in note
    assert "Never asked: it follows from the kind." in note
