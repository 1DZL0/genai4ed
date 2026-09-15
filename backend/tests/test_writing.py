"""Written responses: attempt-first help, the writing supervisor, and scores
the teacher confirms before a student sees them."""

import pytest
from sqlalchemy import select

from app import seed_english
from app.enums import ExceptionKind, Rung, ScoreStatus, TeacherAction, TutorAsk
from app.models import ContractItem, Exception_, RubricScore, TeacherAccessLog
from app.timeline import DEFAULT_TIMELINE
from app.tutor.providers import OverScoringProvider, ParagraphWriterProvider
from app.tutor.writing import (
    WITHHELD_MESSAGE,
    WritingResponse,
    WritingService,
    decide_help,
    get_writing_service,
    review_writing,
)

RUBRIC = {
    "criteria": [
        {"name": "Content", "max": 4, "description": "Argument, reasons, examples"},
        {"name": "Language", "max": 3, "description": "Grammar, formal vocabulary"},
        {"name": "Structure", "max": 3, "description": "Topic sentence, linking words"},
    ]
}
PARAGRAPH = (
    "Salary matters when choosing a job because it gives security. "
    "For example, a nurse with a fair wage can rent a home. Therefore it is important."
)


@pytest.fixture
async def written(db, classroom):
    item = ContractItem(
        contract_id=classroom.contract.id,
        objective_id=classroom.objective.id,
        ordinal=2,
        kind="written_response",
        prompt="Write a paragraph: is salary the most important criterion?",
        expected_answer=None,
        rubric=RUBRIC,
        hint_templates={},
        misconception_vocabulary=[],
    )
    db.add(item)
    await db.commit()
    return item


@pytest.fixture
def use_writer(app):
    def _use(provider):
        app.dependency_overrides[get_writing_service] = lambda: WritingService(provider=provider)

    return _use


def url(classroom, item, action):
    return f"/api/sessions/{classroom.session.id}/items/{item.id}/{action}"


async def ask(client, classroom, item, how, text="", student=None):
    return await client.post(
        url(classroom, item, "ask"),
        json={"ask": how, "text": text},
        headers=classroom.headers(student or classroom.alice),
    )


async def submit(client, classroom, item, text=PARAGRAPH, student=None):
    return await client.post(
        url(classroom, item, "submit"),
        json={"text": text},
        headers=classroom.headers(student or classroom.alice),
    )


async def written_item(client, classroom, item, student=None):
    body = (
        await client.get(
            f"/api/sessions/{classroom.session.id}",
            headers=classroom.headers(student or classroom.alice),
        )
    ).json()
    return next(i for i in body["items"] if i["id"] == str(item.id))


# ---------- the policy, directly ----------


def stuck(level, words, no_progress=False):
    return {"ask": "stuck", "level": level, "words": words, "no_progress": no_progress}


def test_stuck_with_nothing_written_is_asked_to_have_a_go():
    d = decide_help(
        ask=TutorAsk.STUCK, words_now=0, history=[], max_rung=Rung.PARTIAL_STEP, allow_full=False
    )
    assert (d.rung, d.no_progress) == (Rung.ATTEMPT, True)


def test_help_climbs_only_after_new_writing():
    history = [stuck(1, 5)]
    same = decide_help(
        ask=TutorAsk.STUCK,
        words_now=5,
        history=history,
        max_rung=Rung.PARTIAL_STEP,
        allow_full=False,
    )
    more = decide_help(
        ask=TutorAsk.STUCK,
        words_now=9,
        history=history,
        max_rung=Rung.PARTIAL_STEP,
        allow_full=False,
    )
    assert same.rung is Rung.ATTEMPT
    assert more.level == 2


def test_help_fades_after_a_lot_of_independent_writing():
    d = decide_help(
        ask=TutorAsk.STUCK,
        words_now=40,
        history=[stuck(3, 10)],
        max_rung=Rung.PARTIAL_STEP,
        allow_full=False,
    )
    assert d.level == 2


def test_help_never_passes_the_teachers_limit():
    d = decide_help(
        ask=TutorAsk.STUCK,
        words_now=12,
        history=[stuck(2, 10)],
        max_rung=Rung.CONCEPTUAL_CUE,
        allow_full=False,
    )
    assert d.rung is Rung.CONCEPTUAL_CUE


def test_a_sentence_rewrite_is_allowed_only_after_earlier_language_asks():
    language = {"ask": "language", "level": 1, "words": 10, "no_progress": False}
    first = decide_help(
        ask=TutorAsk.LANGUAGE,
        words_now=10,
        history=[],
        max_rung=Rung.PARTIAL_STEP,
        allow_full=False,
    )
    third = decide_help(
        ask=TutorAsk.LANGUAGE,
        words_now=10,
        history=[language, language],
        max_rung=Rung.PARTIAL_STEP,
        allow_full=False,
    )
    assert (first.may_rewrite_sentence, third.may_rewrite_sentence) == (False, True)


@pytest.mark.parametrize("spec", seed_english.ITEMS, ids=["task-1", "task-2"])
def test_the_scenario_1_help_steps_pass_the_writing_supervisor(spec):
    """The teacher's own wording must never be held back as 'writing the work'."""
    for rung, message in spec["hint_templates"].items():
        response = WritingResponse(message=message, rung_used=rung, confidence=0.8)
        assert review_writing(response, ask=TutorAsk.STUCK, permitted=rung, may_rewrite=False) == ()


# ---------- through the API ----------


async def test_the_tutor_asks_for_an_attempt_first(client, classroom, written):
    r = await ask(client, classroom, written, "stuck")
    assert r.status_code == 200
    assert r.json()["message"].startswith("Have a go first")


async def test_a_paragraph_written_by_the_tutor_is_held_back(
    client, db, classroom, written, use_writer
):
    use_writer(ParagraphWriterProvider())
    r = await ask(client, classroom, written, "stuck", text="Salary is important because")
    assert r.json() == {
        "message": WITHHELD_MESSAGE,
        "withheld": True,
        "teacher_notified": True,
    }
    kinds = (await db.scalars(select(Exception_.kind))).all()
    assert ExceptionKind.ASSISTANCE_POLICY_CONFLICT.value in kinds


async def test_asking_again_and_again_without_writing_reaches_the_teacher(
    client, db, classroom, written
):
    for _ in range(3):
        r = await ask(client, classroom, written, "stuck")
    assert r.json()["teacher_notified"] is True
    [exc] = (await db.scalars(select(Exception_))).all()
    assert exc.kind == ExceptionKind.STUCK.value


async def test_tutors_off_blocks_asking_but_not_saving(client, db, classroom, written):
    classroom.contract.timeline = DEFAULT_TIMELINE  # starts on Explanation, tutors off
    classroom.session.phase_index = 0
    await db.commit()

    r = await ask(client, classroom, written, "stuck", text="Some words")
    assert r.status_code == 409
    saved = await client.put(
        url(classroom, written, "draft"),
        json={"text": "Some words"},
        headers=classroom.headers(classroom.alice),
    )
    assert saved.status_code == 204


async def test_a_short_answer_route_refuses_a_written_task(client, classroom, written):
    r = await client.post(
        f"/api/sessions/{classroom.session.id}/attempts",
        json={"item_id": str(written.id), "answer": "yes"},
        headers=classroom.headers(classroom.alice),
    )
    assert r.status_code == 422


async def test_another_students_draft_stays_theirs(client, classroom, written):
    await client.put(
        url(classroom, written, "draft"),
        json={"text": "Alice's words"},
        headers=classroom.headers(classroom.alice),
    )
    assert (await written_item(client, classroom, written, student=classroom.bob))["text"] == ""
    outsider = await client.put(
        url(classroom, written, "draft"),
        json={"text": "hi"},
        headers=classroom.headers(classroom.outsider),
    )
    assert outsider.status_code in (403, 404)


async def test_submitting_creates_a_suggestion_the_student_cannot_see(
    client, db, classroom, written
):
    r = await submit(client, classroom, written)
    assert r.json() == {"submitted": True, "waiting_for_teacher": True}

    [score] = (await db.scalars(select(RubricScore))).all()
    assert score.status == ScoreStatus.SUGGESTED.value
    assert score.suggested_total is not None

    item = await written_item(client, classroom, written)
    assert item["submitted"] is True
    assert item["score"] is None

    again = await submit(client, classroom, written)
    assert again.status_code == 409


async def test_a_score_above_the_rubric_is_refused(client, db, classroom, written, use_writer):
    use_writer(OverScoringProvider())
    await submit(client, classroom, written)
    assert (await db.scalars(select(RubricScore))).all() == []
    [exc] = (await db.scalars(select(Exception_))).all()
    assert exc.kind == ExceptionKind.TUTOR_UNCERTAINTY.value


async def test_the_student_sees_the_score_once_the_teacher_confirms(client, db, classroom, written):
    await submit(client, classroom, written)
    lesson = classroom.session.id
    teacher = classroom.headers(classroom.teacher)

    [waiting] = (
        await client.get(f"/api/teacher/lessons/{lesson}/scores?status=suggested", headers=teacher)
    ).json()
    assert waiting["status"] == "suggested"

    confirmed = await client.post(
        f"/api/teacher/scores/{waiting['id']}/confirm",
        json={"points": {"Content": 4, "Language": 2, "Structure": 3}, "comment": "Good example."},
        headers=teacher,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed_total"] == 9

    score = (await written_item(client, classroom, written))["score"]
    assert (score["total"], score["out_of"], score["comment"]) == (9, 10, "Good example.")

    actions = (await db.scalars(select(TeacherAccessLog.action))).all()
    assert TeacherAction.CONFIRM_SCORE.value in actions


async def test_the_teacher_cannot_give_more_than_a_criterion_allows(client, classroom, written):
    await submit(client, classroom, written)
    teacher = classroom.headers(classroom.teacher)
    [waiting] = (
        await client.get(f"/api/teacher/lessons/{classroom.session.id}/scores", headers=teacher)
    ).json()
    r = await client.post(
        f"/api/teacher/scores/{waiting['id']}/confirm",
        json={"points": {"Language": 7}},
        headers=teacher,
    )
    assert r.status_code == 422


async def test_another_teacher_cannot_see_or_confirm_scores(client, classroom, written):
    await submit(client, classroom, written)
    teacher = classroom.headers(classroom.teacher)
    other = classroom.headers(classroom.other_teacher)
    [waiting] = (
        await client.get(f"/api/teacher/lessons/{classroom.session.id}/scores", headers=teacher)
    ).json()

    listed = await client.get(f"/api/teacher/lessons/{classroom.session.id}/scores", headers=other)
    confirm = await client.post(
        f"/api/teacher/scores/{waiting['id']}/confirm", json={}, headers=other
    )
    assert listed.status_code in (403, 404)
    assert confirm.status_code in (403, 404)


async def test_the_review_shows_a_students_paragraph_and_score(client, classroom, written):
    await ask(client, classroom, written, "stuck")
    await submit(client, classroom, written)
    r = await client.get(
        f"/api/teacher/lessons/{classroom.session.id}/students/{classroom.alice.id}",
        headers=classroom.headers(classroom.teacher),
    )
    assert r.status_code == 200
    body = r.json()
    [work] = body["written"]
    assert work["text"] == PARAGRAPH
    assert work["submitted"] is True
    assert work["score"]["status"] == "suggested"
    assert {"ask", "submitted"} <= {e["kind"] for e in body["events"]}

    cell = next(c for c in body["progress"]["cells"] if c["item_id"] == str(written.id))
    assert (cell["submitted"], cell["score_out_of"], cell["score_confirmed"]) == (True, 10, False)


async def test_plans_accept_written_tasks_with_a_rubric(client, classroom):
    teacher = classroom.headers(classroom.teacher)
    base = {
        "title": "Argumentative paragraphs",
        "subject": "english",
        "objective_code": "ENG-ARG",
        "objective_title": "Argue a point in a paragraph",
        "max_rung": "partial_step",
    }
    good = await client.post(
        "/api/teacher/plans",
        json={
            **base,
            "items": [
                {"kind": "written_response", "prompt": "Write a paragraph.", "rubric": RUBRIC}
            ],
        },
        headers=teacher,
    )
    assert good.status_code == 201, good.text
    missing = await client.post(
        "/api/teacher/plans",
        json={**base, "items": [{"kind": "written_response", "prompt": "Write a paragraph."}]},
        headers=teacher,
    )
    assert missing.status_code == 422
