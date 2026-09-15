"""The per-turn pipeline, through the HTTP surface a student actually uses.

These are the tests the platform's claims rest on: the ladder is climbed one
rung at a time, an over-helpful or answer-leaking model never reaches the
student, a broken provider is a civil reply rather than a 500, and the teacher
is told - with citations - when any of that happens.
"""

from sqlalchemy import select

from app.enums import ConflictCode, EvidenceKind, ExceptionKind, LeakageCheck, ValidationOutcome
from app.models import EvidenceRecord, Exception_, TutorTurn
from app.tutor.providers import (
    AnswerLeakingProvider,
    InvalidDiagnosisProvider,
    MalformedProvider,
    OverHelpfulProvider,
    TimeoutProvider,
    UncertainProvider,
)
from app.tutor.service import WITHHELD_MESSAGE


async def submit(client, classroom, answer, student=None):
    student = student or classroom.alice
    return await client.post(
        f"/api/sessions/{classroom.session.id}/attempts",
        json={"item_id": str(classroom.item.id), "answer": answer},
        headers=classroom.headers(student),
    )


async def turns(db, classroom):
    return (await db.scalars(select(TutorTurn).order_by(TutorTurn.created_at))).all()


async def exceptions(db):
    return (await db.scalars(select(Exception_).order_by(Exception_.priority))).all()


# --- the ordinary path ---------------------------------------------------


async def test_a_correct_answer_is_graded_without_help(client, classroom, db):
    response = await submit(client, classroom, "x = 5")
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is True
    assert body["help_given"] is False
    assert body["attempt_index"] == 1


async def test_a_wrong_answer_earns_the_first_rung_only(client, classroom, db):
    body = (await submit(client, classroom, "4")).json()
    assert body["correct"] is False
    assert body["help_given"] is True
    # The teacher's own diagnostic question for this item.
    assert "collect the x terms" in body["tutor_message"]

    [turn] = await turns(db, classroom)
    assert turn.rung_permitted == "diagnostic_question"
    assert turn.validation_outcome == ValidationOutcome.OK.value
    assert turn.leakage_check == LeakageCheck.PASSED.value


async def test_the_ladder_climbs_one_rung_per_wrong_answer(client, classroom, db):
    for answer in ("4", "6", "7"):
        await submit(client, classroom, answer)

    permitted = [t.rung_permitted for t in await turns(db, classroom)]
    assert permitted == ["diagnostic_question", "conceptual_cue", "targeted_hint"]


async def test_the_attempt_and_the_hint_both_land_in_the_ledger(client, classroom, db):
    await submit(client, classroom, "4")
    records = (await db.scalars(select(EvidenceRecord).order_by(EvidenceRecord.created_at))).all()
    kinds = [r.kind for r in records]
    assert EvidenceKind.ATTEMPT.value in kinds
    assert EvidenceKind.HINT.value in kinds

    attempt = next(r for r in records if r.kind == EvidenceKind.ATTEMPT.value)
    assert attempt.payload["answer"] == "4"
    assert attempt.correct is False
    assert attempt.provenance["source"] == "student"
    assert attempt.purge_after is not None


# --- what must never reach a student -------------------------------------


async def test_an_over_helpful_model_is_not_shown_to_the_student(
    client, classroom, db, use_provider
):
    use_provider(OverHelpfulProvider())
    body = (await submit(client, classroom, "4")).json()

    assert body["tutor_message"] == WITHHELD_MESSAGE
    assert body["help_given"] is False

    [turn] = await turns(db, classroom)
    assert turn.validation_outcome == ValidationOutcome.WITHHELD.value
    assert ConflictCode.RUNG_EXCEEDED.value in turn.conflicts


async def test_a_leaked_answer_never_reaches_the_student(client, classroom, db, use_provider):
    """The headline case. TASD found prompt instructions reduced but did not
    eliminate answer disclosure, so this is checked in output."""
    use_provider(AnswerLeakingProvider(leak="5"))
    body = (await submit(client, classroom, "4")).json()

    assert "5" not in body["tutor_message"]
    assert body["tutor_message"] == WITHHELD_MESSAGE

    [turn] = await turns(db, classroom)
    assert turn.leakage_check == LeakageCheck.FAILED.value
    assert ConflictCode.ANSWER_LEAKAGE.value in turn.conflicts


async def test_a_conflict_reaches_the_teacher_with_citations(client, classroom, db, use_provider):
    use_provider(AnswerLeakingProvider(leak="5"))
    await submit(client, classroom, "4")

    conflict = next(
        e for e in await exceptions(db) if e.kind == ExceptionKind.ASSISTANCE_POLICY_CONFLICT.value
    )
    assert conflict.supporting_record_ids
    assert conflict.payload["conflicts"] == [ConflictCode.ANSWER_LEAKAGE.value]
    # Reported as an observation about the platform, not about the student.
    assert "not shown to the student" in conflict.summary


async def test_a_diagnosis_outside_the_vocabulary_is_refused(client, classroom, db, use_provider):
    use_provider(InvalidDiagnosisProvider())
    body = (await submit(client, classroom, "4")).json()
    assert body["tutor_message"] == WITHHELD_MESSAGE


# --- surviving a broken provider -----------------------------------------


async def test_malformed_output_produces_a_civil_reply_not_a_500(
    client, classroom, db, use_provider
):
    use_provider(MalformedProvider())
    response = await submit(client, classroom, "4")

    assert response.status_code == 200
    assert response.json()["tutor_message"] == WITHHELD_MESSAGE

    [turn] = await turns(db, classroom)
    assert turn.validation_outcome == ValidationOutcome.WITHHELD.value
    assert ConflictCode.MALFORMED_OUTPUT.value in turn.conflicts


async def test_a_provider_timeout_produces_a_civil_reply_not_a_500(
    client, classroom, db, use_provider
):
    use_provider(TimeoutProvider())
    response = await submit(client, classroom, "4")

    assert response.status_code == 200
    assert response.json()["tutor_message"] == WITHHELD_MESSAGE

    [turn] = await turns(db, classroom)
    assert turn.validation_outcome == ValidationOutcome.WITHHELD.value
    assert turn.leakage_check == LeakageCheck.SKIPPED.value


# --- routing the teacher's attention -------------------------------------


async def test_three_wrong_answers_raise_a_repeated_incorrect_exception(client, classroom, db):
    for answer in ("4", "6", "7"):
        body = (await submit(client, classroom, answer)).json()

    assert body["teacher_notified"] is True
    repeated = [e for e in await exceptions(db) if e.kind == ExceptionKind.REPEATED_INCORRECT.value]
    assert len(repeated) == 1
    assert repeated[0].payload["attempts"] == 3
    assert repeated[0].supporting_record_ids


async def test_two_wrong_answers_do_not_disturb_the_teacher(client, classroom, db):
    """The console stays quiet by default; the threshold is the teacher's."""
    for answer in ("4", "6"):
        body = (await submit(client, classroom, answer)).json()
    assert body["teacher_notified"] is False
    assert await exceptions(db) == []


async def test_low_confidence_routes_attention_rather_than_helping_harder(
    client, classroom, db, use_provider
):
    use_provider(UncertainProvider())
    await submit(client, classroom, "4")

    kinds = [e.kind for e in await exceptions(db)]
    assert ExceptionKind.TUTOR_UNCERTAINTY.value in kinds


async def test_a_student_can_ask_for_the_teacher_directly(client, classroom, db):
    response = await client.post(
        f"/api/sessions/{classroom.session.id}/request-teacher",
        headers=classroom.headers(classroom.alice),
    )
    assert response.status_code == 202

    [exc] = await exceptions(db)
    assert exc.kind == ExceptionKind.TEACHER_REQUESTED.value
    # Outranks anything the platform inferred about itself.
    assert exc.priority < 2


# --- isolation, at the HTTP surface --------------------------------------


async def test_a_non_participant_cannot_submit_into_someone_elses_session(client, classroom):
    response = await submit(client, classroom, "5", student=classroom.outsider)
    assert response.status_code == 404


async def test_an_unidentified_caller_is_refused(client, classroom):
    response = await client.post(
        f"/api/sessions/{classroom.session.id}/attempts",
        json={"item_id": str(classroom.item.id), "answer": "5"},
    )
    assert response.status_code == 401


async def test_a_teacher_may_not_submit_as_a_student(client, classroom):
    response = await submit(client, classroom, "5", student=classroom.teacher)
    assert response.status_code == 403


async def test_the_student_view_discloses_that_the_teacher_can_read_it(client, classroom):
    response = await client.get(
        f"/api/sessions/{classroom.session.id}", headers=classroom.headers(classroom.alice)
    )
    assert response.status_code == 200
    body = response.json()
    assert "teacher can read" in body["disclosure"]
    assert [i["prompt"] for i in body["items"]] == [classroom.item.prompt]


async def test_a_student_is_told_which_sessions_are_theirs(client, classroom):
    """Session ids are UUIDs so they cannot be guessed, which means the platform
    has to hand a student their own."""
    response = await client.get("/api/sessions", headers=classroom.headers(classroom.alice))
    assert response.status_code == 200
    [session] = response.json()
    assert session["session_id"] == str(classroom.session.id)
    assert session["title"] == classroom.contract.title
    assert session["items"] == 1


async def test_a_student_is_told_nothing_about_sessions_they_are_not_in(client, classroom):
    response = await client.get("/api/sessions", headers=classroom.headers(classroom.outsider))
    assert response.status_code == 200
    assert response.json() == []
