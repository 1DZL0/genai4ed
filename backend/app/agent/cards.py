"""The cards on the teacher's screen, built from records every time the thread is read.

A card is never stored: the records are, and the card is what they say right now.
"""

import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import classroom
from app.agent.brief import LessonBrief
from app.agent.lessons import (
    classes_of,
    latest_versions,
    live_sessions,
    materials_of,
)
from app.config import get_settings
from app.enums import (
    ContractStatus,
    ExceptionStatus,
    LearningStatus,
    ScoreStatus,
    SessionStatus,
)
from app.models import (
    Class,
    ClassInsight,
    Exception_,
    LearningState,
    LessonContract,
    LessonOutcome,
    Session,
    SessionParticipant,
    User,
)


async def runs_of(db: AsyncSession, plan_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(Session, Class)
            .join(LessonContract, LessonContract.id == Session.contract_id)
            .join(Class, Class.id == Session.class_id)
            .where(LessonContract.plan_id == plan_id)
            .order_by(Session.created_at.desc())
        )
    ).all()
    runs = []
    for session, klass in rows:
        alerts = await db.scalar(
            select(func.count(Exception_.id)).where(
                Exception_.session_id == session.id,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
        waiting = await db.scalar(
            select(func.count(LessonOutcome.id)).where(
                LessonOutcome.session_id == session.id,
                LessonOutcome.status == ScoreStatus.SUGGESTED.value,
            )
        )
        # How it went, at a glance, in the lesson's history on its card.
        students = await db.scalar(
            select(func.count(SessionParticipant.id)).where(
                SessionParticipant.session_id == session.id
            )
        )
        finished = await db.scalar(
            select(func.count(LearningState.id)).where(
                LearningState.session_id == session.id,
                LearningState.status == LearningStatus.COMPLETED.value,
            )
        )
        runs.append(
            {
                "session_id": str(session.id),
                "class_id": str(klass.id),
                "class_label": klass.label,
                "status": session.status,
                "opened_at": classroom.when(session.opened_at),
                "closed_at": classroom.when(session.closed_at),
                "open_alerts": alerts or 0,
                "outcomes_to_confirm": waiting or 0,
                "students": students or 0,
                "took_part": len(await classroom.students_who_wrote(db, session.id)),
                "finished": finished or 0,
            }
        )
    return runs


async def teach_again(
    db: AsyncSession, teacher: User, session: Session, contract: LessonContract
) -> dict | None:
    """What it takes to teach an ended lesson again from where it ended: its approved version
    as it stands now, the teacher's classes, and a lesson running now if there is one (a
    teacher runs one at a time). None when no approved version is left to start."""
    approved = await db.scalar(
        select(LessonContract)
        .where(
            LessonContract.plan_id == contract.plan_id,
            LessonContract.status == ContractStatus.ACTIVE.value,
            LessonContract.archived_at.is_(None),
        )
        .order_by(LessonContract.version.desc())
        .limit(1)
    )
    if approved is None:
        return None
    live = await live_sessions(db, teacher)
    running = await db.get(Class, live[0].class_id) if live else None
    classes = await classes_of(db, teacher)
    return {
        "lesson_id": str(approved.id),
        "taught_class_id": str(session.class_id),
        "classes": [{"id": str(k.id), "label": k.label, "students": n} for k, n in classes],
        "running": running.label if running else None,
    }


def live_run(runs: list[dict]) -> dict | None:
    live = (SessionStatus.OPEN.value, SessionStatus.PAUSED.value)
    return next((r for r in runs if r["status"] in live), None)


async def lesson_card(db: AsyncSession, teacher: User, lesson: LessonContract) -> dict:
    brief = LessonBrief.model_validate(lesson.brief or {})
    approved = await db.scalar(
        select(LessonContract)
        .where(
            LessonContract.plan_id == lesson.plan_id,
            LessonContract.status == ContractStatus.ACTIVE.value,
        )
        .order_by(LessonContract.version.desc())
    )
    runs = await runs_of(db, lesson.plan_id)
    return {
        "type": "lesson",
        "lesson_id": str(lesson.id),
        "plan_id": str(lesson.plan_id),
        "version": lesson.version,
        "status": lesson.status,
        "title": brief.title or lesson.title,
        "subject": brief.subject or lesson.subject,
        "unit": lesson.unit,
        "approach": lesson.approach,
        "units": sorted(
            {c.unit for c in await latest_versions(db, teacher) if c.unit}, key=str.casefold
        ),
        "duration_minutes": brief.duration_minutes,
        "objectives": brief.objectives,
        "strategy": brief.strategy,
        "steps": [
            {
                "name": s.name,
                "kind": s.kind,
                "goal": s.goal,
                "questions": s.prompt_ideas,
                "criteria": s.success_criteria,
                "has_reference": bool(s.reference_answer),
                # The teacher's card only; students never see it.
                "answer": s.reference_answer or None,
                # The depth of thinking the step asks for, 1 to 4, and whether it was set.
                "depth": s.depth,
                "depth_set": s.target_dok is not None,
            }
            for s in brief.steps
        ],
        "key_terms": brief.key_terms,
        "support": brief.support,
        # What the agent filled in itself, until the teacher confirms it by approving.
        "to_check": brief.to_check,
        "assessment": [c.model_dump() for c in brief.assessment],
        "rules_text": brief.rules_text,
        "rules_in_words": brief.rules.describe(),
        "worked_step_after": brief.rules.partial_after_attempts,
        "hints_allowed": brief.rules.hints_allowed,
        "missing": brief.missing(),
        # In a study the researcher assigns this, so the teacher is not offered it.
        "study": get_settings().study_active,
        "approved_lesson_id": str(approved.id) if approved else None,
        "materials": [
            {
                "id": str(m.id),
                "filename": m.filename,
                "readable": bool(m.extracted_text) or m.media_type.startswith("image/"),
            }
            for m in await materials_of(db, lesson.plan_id)
        ],
        "classes": [
            {"id": str(k.id), "label": k.label, "students": n}
            for k, n in await classes_of(db, teacher)
        ],
        "live": live_run(runs),
        "runs": runs,
    }


async def lessons_card(db: AsyncSession, teacher: User) -> dict:
    lessons = []
    plans = {
        plan_id: (first, approved)
        for plan_id, first, approved in (
            await db.execute(
                select(
                    LessonContract.plan_id,
                    func.min(LessonContract.created_at),
                    func.bool_or(LessonContract.status == ContractStatus.ACTIVE.value),
                )
                .where(
                    LessonContract.teacher_id == teacher.id,
                    LessonContract.archived_at.is_(None),
                )
                .group_by(LessonContract.plan_id)
            )
        ).all()
    }
    for c in await latest_versions(db, teacher):
        brief = LessonBrief.model_validate(c.brief or {})
        runs = await runs_of(db, c.plan_id)
        closed = [r for r in runs if r["status"] == SessionStatus.CLOSED.value]
        lessons.append(
            {
                "lesson_id": str(c.id),
                "plan_id": str(c.plan_id),
                "title": brief.title or c.title,
                "subject": brief.subject or c.subject,
                "unit": c.unit,
                "approach": c.approach,
                "status": c.status,
                "steps": len(brief.steps),
                "duration_minutes": brief.duration_minutes,
                "ready": not brief.missing(),
                "live": live_run(runs),
                "last_run": closed[0] if closed else None,
                # An approved version exists, so a draft on top of it is a change to approve.
                "approved": bool(plans.get(c.plan_id, (None, False))[1]),
                # Order inside a unit: when the lesson was first made, not its latest edit.
                "created_at": classroom.when(plans.get(c.plan_id, (c.created_at, False))[0]),
            }
        )
    return {
        "type": "lessons",
        "lessons": lessons,
        "classes": [
            {"id": str(k.id), "label": k.label, "students": n}
            for k, n in await classes_of(db, teacher)
        ],
    }


async def class_card(db: AsyncSession, session: Session, teacher: User) -> dict:
    p = await classroom.pulse(db, session)
    klass = await db.get(Class, session.class_id)
    contract = await db.get(LessonContract, session.contract_id)
    ended = session.status == SessionStatus.CLOSED.value
    return {
        "teach_again": await teach_again(db, teacher, session, contract) if ended else None,
        "type": "class",
        "session_id": str(session.id),
        "lesson_id": str(contract.id),
        "title": p.brief.title or contract.title,
        "class_label": klass.label if klass else "",
        "status": session.status,
        "opened_at": classroom.when(session.opened_at),
        "closes_at": classroom.when(session.closes_at),
        "steps": [s.name for s in p.brief.steps],
        "students": [s.model_dump(mode="json") for s in p.students],
        "alerts": [a.model_dump(mode="json") for a in p.alerts],
        "patterns": [pt.model_dump() for pt in p.patterns],
        "notable": [n.model_dump(mode="json") for n in p.notable],
    }


async def outcomes_card(db: AsyncSession, session: Session, teacher: User) -> dict:
    contract = await db.get(LessonContract, session.contract_id)
    brief = LessonBrief.model_validate(contract.brief or {})
    klass = await db.get(Class, session.class_id)
    out_of = sum(c.max for c in brief.assessment)
    rows = (
        await db.scalars(
            select(LessonOutcome)
            .where(LessonOutcome.session_id == session.id)
            .order_by(LessonOutcome.created_at)
        )
    ).all()
    p = await classroom.pulse(db, session)
    wrote = await classroom.students_who_wrote(db, session.id)
    took_part = bool(wrote)
    names = {s.student_id: s.pseudonym for s in p.students}
    outcomes = sorted(
        (
            {
                "id": str(o.id),
                "student_id": str(o.student_id),
                "pseudonym": names.get(o.student_id, "unknown"),
                "status": o.status,
                "suggested": o.suggested,
                "suggested_total": o.suggested_total,
                "confirmed": o.confirmed,
                "confirmed_total": o.confirmed_total,
                "comment": o.comment,
                "out_of": out_of,
            }
            for o in rows
        ),
        key=lambda o: o["pseudonym"],
    )
    have = {o["student_id"] for o in outcomes}
    summary = await db.scalar(
        select(ClassInsight.summary)
        .where(ClassInsight.session_id == session.id)
        .order_by(ClassInsight.created_at.desc())
        .limit(1)
    )
    return {
        "type": "outcomes",
        "session_id": str(session.id),
        "title": brief.title or contract.title,
        "class_label": klass.label if klass else "",
        "status": session.status,
        "summary": summary,
        "criteria": [c.model_dump() for c in brief.assessment],
        "outcomes": outcomes,
        "students_without_outcome": [
            s.pseudonym
            for s in p.students
            if str(s.student_id) not in have and s.student_id in wrote
        ],
        # Still open after the end, so they are not lost once the class board is gone.
        "alerts": [a.model_dump(mode="json") for a in p.alerts],
        # Nothing to judge is different from nothing judged yet; the card says which.
        "took_part": took_part,
        "can_suggest": session.status == SessionStatus.CLOSED.value and took_part,
        "marked": bool(brief.assessment),
        "teach_again": (
            await teach_again(db, teacher, session, contract)
            if session.status == SessionStatus.CLOSED.value
            else None
        ),
    }


async def build_card(db: AsyncSession, teacher: User, card: dict | None) -> dict | None:
    """Fill in a card the agent or a button asked for; None if its record has gone."""
    if not card:
        return None
    kind = card.get("type")
    if kind == "lessons":
        return await lessons_card(db, teacher)
    if kind == "lesson":
        lesson = await db.get(LessonContract, uuid.UUID(card["lesson_id"]))
        if lesson is None or lesson.teacher_id != teacher.id or lesson.archived_at is not None:
            return None
        return await lesson_card(db, teacher, lesson)
    session = (
        await db.get(Session, uuid.UUID(card["session_id"])) if card.get("session_id") else None
    )
    if session is None:
        return None
    klass = await db.get(Class, session.class_id)
    if klass is None or klass.teacher_id != teacher.id:
        return None
    if kind == "class":
        return await class_card(db, session, teacher)
    if kind == "student":
        student = await db.get(User, uuid.UUID(card["student_id"]))
        if student is None:
            return None
        view = await classroom.student_view(
            db, session, student, conversation=bool(card.get("conversation"))
        )
        return {"type": "student", "session_id": str(session.id), **view}
    if kind == "outcomes":
        return await outcomes_card(db, session, teacher)
    return None


async def strip(db: AsyncSession, teacher: User) -> list[dict]:
    """One row of counts per lesson running now."""
    rows = []
    for session in await live_sessions(db, teacher):
        p = await classroom.pulse(db, session)
        klass = await db.get(Class, session.class_id)
        first: dict[uuid.UUID, classroom.Alert] = {}
        for a in p.alerts:
            first.setdefault(a.student_id, a)
        rows.append(
            {
                "session_id": str(session.id),
                "title": p.brief.title,
                "class_label": klass.label if klass else "",
                "status": session.status,
                "closes_at": classroom.when(session.closes_at),
                "counts": dict(Counter(s.state for s in p.students)),
                "students": len(p.students),
                "needs_you": [
                    {
                        "exception_id": str(a.id),
                        "student_id": str(a.student_id),
                        "pseudonym": a.pseudonym,
                        "kind": a.kind,
                        "summary": a.summary,
                    }
                    for a in list(first.values())[:4]
                ],
                "needs_you_more": max(0, len(first) - 4),
            }
        )
    return rows
