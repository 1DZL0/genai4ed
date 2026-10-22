"""The buttons about a class in a lesson: the board, a student, pause, resume and end,
the outcomes, alerts dealt with, and guidance for one student."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select

from app.agent import classroom, store, thread
from app.agent.llm import LLMError
from app.auth import teacher_session
from app.enums import (
    Audience,
    EvidenceKind,
    ExceptionStatus,
    MessageRole,
    ScoreStatus,
    SessionStatus,
    TeacherAction,
)
from app.events import broker
from app.ledger import append
from app.models import (
    Exception_,
    LessonContract,
    LessonOutcome,
)
from app.routers import learn as learn_router
from app.routers import teacher as teacher_router
from app.routers.thread_common import (
    log_access,
    mark_focus,
    need,
    student_in,
)


async def show_class(db, teacher, body, agent):
    session = await teacher_session(need(body.session_id, "A lesson"), teacher, db)
    log_access(db, teacher, TeacherAction.REVIEW_STUDENT, session.id, detail={"view": "class"})
    await mark_focus(db, teacher, session_id=str(session.id))
    await db.commit()
    return {"type": "class", "session_id": str(session.id)}


async def show_student(db, teacher, body, agent):
    session = await teacher_session(need(body.session_id, "A lesson"), teacher, db)
    student = await student_in(db, session, need(body.student_id, "A student"))
    log_access(db, teacher, TeacherAction.REVIEW_STUDENT, session.id, student.id)
    await db.commit()
    return {
        "type": "student",
        "session_id": str(session.id),
        "student_id": str(student.id),
    }


async def show_transcript(db, teacher, body, agent):
    """Reading a student's transcript is deliberate, and logged as such."""
    session = await teacher_session(need(body.session_id, "A lesson"), teacher, db)
    student = await student_in(db, session, need(body.student_id, "A student"))
    log_access(db, teacher, TeacherAction.TRANSCRIPT_DRILLDOWN, session.id, student.id)
    await db.commit()
    return {
        "type": "student",
        "session_id": str(session.id),
        "student_id": str(student.id),
        "conversation": True,
    }


async def show_outcomes(db, teacher, body, agent):
    session = await teacher_session(need(body.session_id, "A lesson"), teacher, db)
    return {"type": "outcomes", "session_id": str(session.id)}


async def change_state(db, teacher, body, agent, *, to: SessionStatus, said: str):
    """Pause, resume or end; `said` is the event line, with {title}, or blank for a mark."""
    session = await teacher_session(need(body.session_id, "A lesson"), teacher, db)
    await teacher_router.set_state(session.id, to, teacher, db)
    if said:
        contract = await db.get(LessonContract, session.contract_id)
        title = contract.title if contract else "the lesson"
        text = said.format(title=title)
        if to is SessionStatus.CLOSED:
            text += await still_open(db, session.id)
        await thread.event(db, teacher, text=text, session_id=str(session.id))
    else:
        await mark_focus(db, teacher, session_id=str(session.id))
    await db.commit()
    return (
        {"type": "outcomes", "session_id": str(session.id)}
        if to is SessionStatus.CLOSED
        else {"type": "class", "session_id": str(session.id)}
    )


async def still_open(db, session_id) -> str:
    """A sentence on the alerts still open in a lesson that has just ended, or nothing."""
    kinds = (
        await db.scalars(
            select(Exception_.kind).where(
                Exception_.session_id == session_id,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
    ).all()
    if not kinds:
        return ""
    worst = " including a wellbeing concern" if "safeguarding" in kinds else ""
    n = len(kinds)
    return (
        f" {n} alert{'s are' if n != 1 else ' is'} still open{worst}: "
        f"{'they are' if n != 1 else 'it is'} on the outcomes card."
    )


async def suggest_outcomes(db, teacher, body, agent):
    session = await teacher_session(need(body.session_id, "A lesson"), teacher, db)
    if session.status != SessionStatus.CLOSED.value:
        raise HTTPException(status_code=409, detail="End the lesson before reviewing outcomes.")
    try:
        suggested = await classroom.suggest_outcomes(db, agent, session=session)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail="The agent couldn't review just now.") from exc
    said = (
        "The summary of the lesson and a note on each student, for you to confirm."
        if suggested
        else "Nothing to sum up for this lesson: no student took part in it."
    )
    await thread.event(db, teacher, text=said, session_id=str(session.id))
    await db.commit()
    return {"type": "outcomes", "session_id": str(session.id)}


async def confirm_outcome(db, teacher, body, agent):
    """The teacher's decision; their points replace the suggestion where given."""
    session = await teacher_session(need(body.session_id, "A lesson"), teacher, db)
    outcome = await db.get(LessonOutcome, need(body.outcome_id, "An outcome"))
    if outcome is None or outcome.session_id != session.id:
        raise HTTPException(status_code=404, detail="Outcome not found.")
    chosen = []
    for c in outcome.suggested.get("criteria", []):
        value = body.points.get(c["name"], c["points"])
        if not 0 <= value <= int(c["max"]):
            raise HTTPException(
                status_code=422, detail=f"{c['name']} must be between 0 and {c['max']}."
            )
        # A reason written for other points is not the reason for these.
        reason = c.get("reason", "") if value == c["points"] else ""
        chosen.append({**c, "points": value, "reason": reason})
    outcome.confirmed = {
        "criteria": chosen,
        "keep": outcome.suggested.get("keep", ""),
        "develop": outcome.suggested.get("develop", []),
    }
    outcome.confirmed_total = sum(c["points"] for c in chosen)
    outcome.comment = body.comment
    outcome.status = ScoreStatus.CONFIRMED.value
    outcome.confirmed_by = teacher.id
    outcome.confirmed_at = datetime.now(UTC)
    log_access(
        db,
        teacher,
        TeacherAction.CONFIRM_SCORE,
        session.id,
        outcome.student_id,
        {"suggested": outcome.suggested_total, "confirmed": outcome.confirmed_total},
    )
    left = await db.scalar(
        select(func.count(LessonOutcome.id)).where(
            LessonOutcome.session_id == session.id,
            LessonOutcome.status != ScoreStatus.CONFIRMED.value,
        )
    )
    if not left:
        done = await db.scalar(
            select(func.count(LessonOutcome.id)).where(LessonOutcome.session_id == session.id)
        )
        await thread.event(
            db,
            teacher,
            text=(
                "Confirmed the outcome for 1 student."
                if done == 1
                else f"Confirmed the outcomes for {done} students."
            ),
            session_id=str(session.id),
        )
    await db.commit()
    return {"type": "outcomes", "session_id": str(session.id)}


async def acknowledge(db, teacher, body, agent):
    """Dealt with: the card on screen stays up, one alert lighter, wherever it was pressed (the
    class board, a student's card, or the outcomes card with marks still being typed)."""
    alert = await db.get(Exception_, need(body.exception_id, "An alert"))
    session_id = alert.session_id if alert is not None else None
    await teacher_router.acknowledge(body.exception_id, teacher, db)
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    if conversation.showing is None and session_id:
        return {"type": "class", "session_id": str(session_id)}
    # None keeps what was last shown; it is rebuilt from the records, without this alert.
    return None


async def guide(db, teacher, body, agent):
    """Tell the agent how to teach this student, and the student too if chosen."""
    session = await teacher_session(need(body.session_id, "A lesson"), teacher, db)
    student = await student_in(db, session, need(body.student_id, "A student"))
    if session.status == SessionStatus.CLOSED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "This lesson has ended, so the agent can't act on that. Your note for this "
                "student goes with their outcome on the outcomes card."
            ),
        )
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Say what the agent should do.")
    await append(
        db,
        session_id=session.id,
        student_id=student.id,
        kind=EvidenceKind.TEACHER_GUIDANCE,
        payload={"text": text, "shown_to_student": body.show_to_student},
        provenance={"source": "teacher", "teacher_id": str(teacher.id)},
    )
    convo = await store.student_conversation(db, session_id=session.id, student_id=student.id)
    await store.add_message(
        db,
        convo,
        role=MessageRole.EVENT,
        audience=Audience.ALL if body.show_to_student else Audience.TEACHER,
        text=(
            f"From your teacher: {text}"
            if body.show_to_student
            else f"Teacher guidance for the agent: {text}"
        ),
    )
    log_access(
        db,
        teacher,
        TeacherAction.GUIDE_STUDENT,
        session.id,
        student.id,
        {"shown_to_student": body.show_to_student},
    )
    await db.commit()
    # The agent acts on it now, not whenever the student next happens to write.
    acted = False
    if session.status == SessionStatus.OPEN.value:
        try:
            await learn_router._turn(db, agent, session, student, None, None, guidance=text)
            acted = True
        except HTTPException:
            await db.rollback()
    said = f"Sent {student.pseudonym} your note. " if body.show_to_student else ""
    await thread.event(
        db,
        teacher,
        text=said
        + (
            f"The agent has written to {student.pseudonym} to do as you asked."
            if acted
            else (
                f"The agent will do as you asked once you resume and {student.pseudonym} writes."
                if session.status == SessionStatus.PAUSED.value
                else f"The agent will do as you asked when {student.pseudonym} next writes."
            )
        ),
        session_id=str(session.id),
    )
    await db.commit()
    await broker.publish(session.id, {"type": "guidance", "student": student.pseudonym})
    return {
        "type": "student",
        "session_id": str(session.id),
        "student_id": str(student.id),
    }
