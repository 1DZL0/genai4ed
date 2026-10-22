"""The buttons about a lesson: show it, approve it, start it, remove it, its unit and its
teaching approach, and a preview of how it opens for a student."""

import re
import unicodedata
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from app.agent import approaches, lessons, store, student_mode, thread
from app.agent.brief import LessonBrief
from app.agent.llm import LLMError
from app.agent.policy import PolicyRules
from app.enums import (
    ContractStatus,
    ExceptionStatus,
    LeakageCheck,
    SessionStatus,
    ValidationOutcome,
)
from app.models import (
    AgentTurn,
    Class,
    Exception_,
    LessonContract,
    Material,
    Message,
    Session,
    SessionParticipant,
)
from app.routers import lessons as lessons_router
from app.routers import teacher as teacher_router
from app.routers.thread_common import (
    current_focus,
    mark_focus,
    need,
    owned_lesson,
    versions_of,
)


async def show_lesson(db, teacher, body, agent):
    lesson = await owned_lesson(db, teacher, need(body.lesson_id, "A lesson"))
    await mark_focus(db, teacher, lesson_id=str(lesson.id))
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def show_lessons(db, teacher, body, agent):
    return {"type": "lessons"}


async def delete_material(db, teacher, body, agent):
    """Take a file back off the agent; the lesson card simply loses it."""
    material = await db.get(Material, need(body.material_id, "A file"))
    if material is None or material.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="File not found.")
    plan = material.plan_id
    await db.delete(material)
    await db.commit()
    lesson = await db.scalar(
        select(LessonContract)
        .where(LessonContract.plan_id == plan, LessonContract.archived_at.is_(None))
        .order_by(LessonContract.version.desc())
    )
    return {"type": "lesson", "lesson_id": str(lesson.id)} if lesson else None


async def follow_up(db, teacher, body, agent):
    """A shared difficulty becomes a request for a new lesson, drafted like any other."""
    note = body.text.strip()
    if not note:
        raise HTTPException(status_code=422, detail="Say which difficulty to follow up.")
    try:
        reply = await thread.respond(
            db,
            agent,
            teacher=teacher,
            text=(
                "Several students share a difficulty. Draft a new lesson, a short "
                f"follow-up activity about {note}."
            ),
            force_new=True,
        )
    except thread.ThreadUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="The agent couldn't draft it just now."
        ) from exc
    return reply.data.get("card")


async def clear_thread(db, teacher, body, agent):
    """Delete the talk; lessons, evidence and the audit trail stay."""
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    await db.execute(delete(Message).where(Message.conversation_id == conversation.id))
    conversation.showing = None
    await db.commit()
    return None


async def start_new_lesson(db, teacher, body, agent):
    """Clear the focus and the card, so the next thing said starts a new lesson."""
    await thread.event(db, teacher, text="", clears_focus=True)
    (await store.teacher_thread(db, teacher_id=teacher.id)).showing = None
    await db.commit()
    return None


async def preview_lesson(db, teacher, body, agent):
    """How step 1 would open for a student, from the draft as it stands, written into the
    thread. Nothing reaches any student; one model call."""
    lesson = await owned_lesson(db, teacher, need(body.lesson_id, "A lesson"))
    brief = LessonBrief.model_validate(lesson.brief or {})
    if not brief.steps:
        raise HTTPException(status_code=422, detail="Give the lesson a first step to preview.")
    try:
        out, result = await student_mode.preview_opening(
            agent, brief=brief, approach=lesson.approach
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=f"No preview this time: {exc}") from exc
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    db.add(
        AgentTurn(
            conversation_id=conversation.id,
            mode="preview",
            context_manifest={"mode": "preview", "lesson_id": str(lesson.id)},
            policy_version=student_mode.POLICY_VERSION,
            prompt_version=student_mode.prompt_version(),
            provider=result.provider,
            model=result.model,
            latency_ms=result.latency_ms,
            validation_outcome=ValidationOutcome.OK.value,
            leakage_check=LeakageCheck.SKIPPED.value,
            conflicts=[],
            request={"preview": True},
            response={"raw": result.raw[:6000]},
        )
    )
    await thread.event(
        db,
        teacher,
        text=f"How step 1 would open for a student, as the lesson stands:\n\n{out.message}",
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def approve(db, teacher, body, agent):
    """Record the teacher's approval; only now can the agent teach from this brief."""
    lesson = await owned_lesson(db, teacher, need(body.lesson_id, "A lesson"))
    if lesson.status != ContractStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="This version is already approved.")
    brief = LessonBrief.model_validate(lesson.brief or {})
    if brief.missing():
        raise HTTPException(
            status_code=422,
            detail="Before approving, the lesson needs " + ", ".join(brief.missing()) + ".",
        )
    await db.execute(
        update(LessonContract)
        .where(
            LessonContract.plan_id == lesson.plan_id,
            LessonContract.id != lesson.id,
            LessonContract.status == ContractStatus.ACTIVE.value,
        )
        .values(status=ContractStatus.CLOSED.value)
    )
    lesson.status = ContractStatus.ACTIVE.value
    lesson.activated_at = datetime.now(UTC)
    lesson.activated_by = teacher.id
    lesson.title = brief.title.strip()[:255] or lesson.title
    lesson.subject = brief.subject.strip()[:64] or lesson.subject
    if brief.to_check:
        # Approval is the teacher confirming everything the agent filled in.
        brief.to_check = []
        lesson.brief = brief.model_dump(mode="json")
    running_older = await db.scalar(
        select(func.count(Session.id))
        .join(LessonContract, LessonContract.id == Session.contract_id)
        .where(
            LessonContract.plan_id == lesson.plan_id,
            Session.contract_id != lesson.id,
            Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
        )
    )
    await thread.event(
        db,
        teacher,
        text=(
            f"Approved “{lesson.title}”. The class running now keeps the earlier version; the "
            "next start uses this one."
            if running_older
            else f"Approved “{lesson.title}”. The agent will teach it exactly as it stands."
        ),
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def run(db, teacher, body, agent):
    """Start the lesson with a class now; one at a time, even when Start is pressed twice."""
    if teacher.id in starting:
        raise HTTPException(status_code=409, detail="Already starting a lesson. Give it a moment.")
    starting.add(teacher.id)
    try:
        return await start_with_class(db, teacher, body)
    finally:
        starting.discard(teacher.id)


# shortcut: one API process, so an in-memory set serialises Start per teacher; use a database
# lock if the API ever runs as several processes.
starting: set[uuid.UUID] = set()


async def start_with_class(db, teacher, body):
    lesson = await owned_lesson(db, teacher, need(body.lesson_id, "A lesson"))
    if lesson.status != ContractStatus.ACTIVE.value:
        approved = next(
            (
                v
                for v in reversed(await versions_of(db, lesson.plan_id))
                if v.status == ContractStatus.ACTIVE.value
            ),
            None,
        )
        if approved is None:
            raise HTTPException(status_code=409, detail="Approve the lesson before running it.")
        lesson = approved
    klass = await db.get(Class, need(body.class_id, "A class"))
    if klass is None or klass.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Class not found.")
    # A teacher runs one lesson at a time.
    running = (
        await db.execute(
            select(Session, Class)
            .join(Class, Class.id == Session.class_id)
            .where(
                Class.teacher_id == teacher.id,
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
        )
    ).first()
    if running is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"You already have a lesson running with {running[1].label}. End that one first."
            ),
        )
    booked = await lessons_router.book_lesson(
        lessons_router.LessonIn(plan_version_id=lesson.id, class_id=klass.id), teacher, db
    )
    started = await lessons_router.start_lesson(booked.lesson_id, teacher, db)
    await thread.event(
        db,
        teacher,
        text=(
            f"Started with {klass.label}: {started.students} "
            f"student{'s' if started.students != 1 else ''}, {started.steps} "
            f"step{'s' if started.steps != 1 else ''}."
        ),
        session_id=str(started.lesson_id),
    )
    await db.commit()
    return {"type": "class", "session_id": str(started.lesson_id)}


async def delete_lesson(db, teacher, body, agent):
    """A lesson never taught is deleted with its files; one that has been taught is archived.
    Not while one of its classes still has an alert open: that would leave a student who asked
    for the teacher, or was upset, with nobody to see it."""
    lesson = await owned_lesson(db, teacher, need(body.lesson_id, "A lesson"))
    versions = await versions_of(db, lesson.plan_id)
    ids = [v.id for v in versions]
    waiting = await db.scalar(
        select(func.count(Exception_.id))
        .join(Session, Session.id == Exception_.session_id)
        .where(Session.contract_id.in_(ids), Exception_.status == ExceptionStatus.OPEN.value)
    )
    if waiting:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{waiting} alert{'s' if waiting != 1 else ''} from this lesson still "
                f"need{'' if waiting != 1 else 's'} you. Press Dealt with on "
                f"{'each' if waiting != 1 else 'it'} (on the class or the outcomes card), "
                "then remove the lesson."
            ),
        )
    # A run still going ends with the lesson; nothing should keep running with no lesson behind it.
    live = (
        await db.scalars(
            select(Session).where(
                Session.contract_id.in_(ids),
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
        )
    ).all()
    ended_for = 0
    for session in live:
        ended_for += (
            await db.scalar(
                select(func.count(SessionParticipant.id)).where(
                    SessionParticipant.session_id == session.id
                )
            )
            or 0
        )
        await teacher_router.set_state(session.id, SessionStatus.CLOSED, teacher, db)
    focus = await current_focus(db, teacher)
    in_focus = focus.lesson is not None and focus.lesson.plan_id == lesson.plan_id
    taught = await db.scalar(select(func.count(Session.id)).where(Session.contract_id.in_(ids)))
    if taught:
        now = datetime.now(UTC)
        for v in versions:
            v.archived_at = now
    else:
        await db.execute(delete(Material).where(Material.plan_id == lesson.plan_id))
        for v in versions:
            await db.delete(v)
    title = LessonBrief.model_validate(lesson.brief or {}).title or lesson.title
    said = f"Removed “{title}”."
    if live:
        who = f"{ended_for} student{'s' if ended_for != 1 else ''}"
        said += f" It was running, so it has ended for {who}."
    # Removing another lesson from the list leaves the one being worked on in focus.
    await thread.event(db, teacher, text=said, clears_focus=in_focus)
    await db.commit()
    return {"type": "lessons"} if in_focus else None


async def set_unit(db, teacher, body, agent):
    """Put a lesson in a unit by name, or take it out. Every version of it moves together. A
    name the teacher has used before, in any case, is reused as they first spelled it."""
    lesson = await owned_lesson(db, teacher, need(body.lesson_id, "A lesson"))
    # Invisible characters (zero-width spaces and the like) never make a different unit.
    visible = "".join(ch for ch in body.text if unicodedata.category(ch) != "Cf")
    name = " ".join(visible.split())[:80].rstrip() or None
    if name:
        used = (
            await db.scalars(
                select(LessonContract.unit)
                .where(
                    LessonContract.teacher_id == teacher.id,
                    LessonContract.archived_at.is_(None),
                    LessonContract.unit.is_not(None),
                )
                .distinct()
            )
        ).all()
        name = {u.casefold(): u for u in used}.get(name.casefold(), name)
    for v in await versions_of(db, lesson.plan_id):
        v.unit = name
    title = LessonBrief.model_validate(lesson.brief or {}).title or lesson.title
    await thread.event(
        db,
        teacher,
        text=f"Put “{title}” in the unit {name}." if name else f"Took “{title}” out of its unit.",
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def set_approach(db, teacher, body, agent):
    """Tag a lesson with the teaching approach it is to be taught by, with the rule that goes
    with it, or take the tag off. Like any change to an approved lesson it makes a new version
    to approve: the approved version, a class running now and every run already taught keep
    the approach they had."""
    lesson = await owned_lesson(db, teacher, need(body.lesson_id, "A lesson"))
    name = body.text.strip().lower() or None
    if name is not None and name not in approaches.NAMES:
        raise HTTPException(status_code=422, detail="The approach is direct or inquiry.")
    current = await lessons.current_version(db, lesson.plan_id) or lesson
    draft = await lessons.draft_to_work_on(db, current)
    draft.approach = name
    if name:
        brief = LessonBrief.model_validate(draft.brief or {})
        brief.rules = brief.rules.model_copy(update=approaches.RULES[name])
        brief.rules_text = approaches.rules_text_for(brief.rules_text, name)
        draft.brief = brief.model_dump(mode="json")
    approved = any(
        v.status == ContractStatus.ACTIVE.value for v in await versions_of(db, lesson.plan_id)
    )
    title = LessonBrief.model_validate(draft.brief or {}).title or draft.title
    said = (
        f"“{title}” is to be taught by {approaches.NAMES[name]}."
        if name
        else f"Took the teaching approach off “{title}”."
    )
    if approved:
        said += " That is a change: approve it to use it."
    await thread.event(db, teacher, text=said, lesson_id=str(draft.id))
    await db.commit()
    return {"type": "lesson", "lesson_id": str(draft.id)}


async def start_approach(db, teacher, body, agent):
    """A new lesson to be taught by the chosen approach, with its rule already set. From here
    the agent is told the approach while it drafts, and again on every turn with a student. An
    empty draft from an earlier press is reused rather than piling up."""
    name = body.text.strip().lower()
    if name not in approaches.NAMES:
        raise HTTPException(status_code=422, detail="The approach is direct or inquiry.")
    lesson = await lessons.empty_draft_of(db, teacher) or lessons.new_lesson(db, teacher)
    lesson.approach = name
    lesson.brief = LessonBrief(
        rules=PolicyRules(**approaches.RULES[name]),
        rules_text=approaches.RULE_WORDS[name],
    ).model_dump(mode="json")
    await db.flush()
    await thread.event(
        db,
        teacher,
        text=(
            f"A new lesson, to be taught by {approaches.NAMES[name]}. Describe it and the agent "
            "builds it that way."
        ),
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def copy_with_approach(db, teacher, body, agent):
    """The same lesson again, to be taught by the other approach: identical steps, questions,
    answers, marks and files; only the approach, its rule and the title's ending differ."""
    picked = await owned_lesson(db, teacher, need(body.lesson_id, "A lesson"))
    name = body.text.strip().lower()
    if name not in approaches.NAMES:
        raise HTTPException(status_code=422, detail="The approach is direct or inquiry.")
    # The lesson as it stands now, not whichever version the button was pressed on.
    source = await lessons.current_version(db, picked.plan_id) or picked
    brief = LessonBrief.model_validate(source.brief or {})
    base = APPROACH_SUFFIX.sub("", brief.title or source.title).strip()
    suffix = f" ({approaches.NAMES[name]})"
    brief.title = base[: 255 - len(suffix)].rstrip() + suffix
    brief.rules = brief.rules.model_copy(update=approaches.RULES[name])
    brief.rules_text = approaches.rules_text_for(brief.rules_text, name)
    # Checked before it is saved: a copy the platform can't read would break the thread.
    brief = LessonBrief.model_validate(brief.model_dump(mode="json"))
    copy = LessonContract(
        plan_id=uuid.uuid4(),
        teacher_id=teacher.id,
        title=brief.title,
        subject=source.subject,
        status=ContractStatus.DRAFT.value,
        version=1,
        brief=brief.model_dump(mode="json"),
        use_past_lessons=source.use_past_lessons,
        unit=source.unit,
        approach=name,
    )
    db.add(copy)
    await db.flush()
    for m in await lessons.materials_of(db, source.plan_id):
        db.add(
            Material(
                teacher_id=teacher.id,
                plan_id=copy.plan_id,
                filename=m.filename,
                media_type=m.media_type,
                size_bytes=m.size_bytes,
                content=m.content,
                extracted_text=m.extracted_text,
            )
        )
    await thread.event(
        db,
        teacher,
        text=(
            f"Made “{brief.title}”: the same steps, questions, marks and files, to be taught by "
            f"{approaches.NAMES[name]}. Approve it when you are ready."
        ),
        lesson_id=str(copy.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(copy.id)}


# The approach a copy's title ends with, in any case, so copying a copy does not stack them.
APPROACH_SUFFIX = re.compile(r"\s*\((?:direct instruction|guided inquiry)\)\s*$", re.IGNORECASE)
