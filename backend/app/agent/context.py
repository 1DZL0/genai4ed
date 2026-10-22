"""What the class agent is shown when teaching one student, and nothing more.

The context is built from the approved brief, the teacher's rules and guidance,
and this student's own record; the ids of everything used come back as a manifest.
The prose, the scaffold blocks and the version live in `scaffold`; this module gathers
the record and fills the slots. The earlier prose (v8) is kept so the two can be compared
on one bench; `Settings.student_prompt` picks.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import approaches, memory, prompt_v8, scaffold, store
from app.agent.brief import LessonBrief
from app.config import get_settings
from app.enums import (
    DISCLOSURE_ORDER,
    Audience,
    Disclosure,
    EvidenceKind,
    ExceptionKind,
    ExceptionStatus,
    LearningStatus,
    MessageRole,
    SignalKind,
)
from app.models import (
    Conversation,
    EvidenceRecord,
    Exception_,
    LearningState,
    LessonContract,
    Session,
    User,
)
from app.study import LADDER, RUNG_WORDS

CONVERSATION_WINDOW = 30


@dataclass
class Context:
    system: str
    messages: list[dict]
    manifest: dict = field(default_factory=dict)


# The fixed prose as the research page shows it, slots named.
STUDENT_SYSTEM = scaffold.fixed_text(depth=True)


# The label the scripted demo responder reads the student's position from.


def prompt_set() -> str:
    chosen = (get_settings().student_prompt or "v10").lower()
    return chosen if chosen in ("v8", "v9", "v10") else "v10"


def _bare(text: str) -> bool:
    """A bare answer: a few tokens with a number in them and no working."""
    tokens = text.split()
    return 0 < len(tokens) <= 3 and any(ch.isdigit() for ch in text)


def _bare_streak(history: list) -> tuple[int, int | None]:
    """How many of the student's latest messages in a row were bare answers, and the typical
    seconds between them."""
    said = [m for m in history if m.role == MessageRole.STUDENT.value]
    streak = []
    for m in reversed(said):
        if not _bare(m.text):
            break
        streak.append(m)
    if len(streak) < 2:
        return len(streak), None
    gaps = [
        (a.created_at - b.created_at).total_seconds()
        for a, b in zip(streak[:-1], streak[1:], strict=False)
    ]
    return len(streak), int(sum(gaps) / len(gaps)) if gaps else None


async def _asked_teacher_open(db: AsyncSession, session_id, student_id) -> bool:
    return (
        await db.scalar(
            select(Exception_.id).where(
                Exception_.session_id == session_id,
                Exception_.student_id == student_id,
                Exception_.kind == ExceptionKind.TEACHER_REQUESTED.value,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
    ) is not None


async def _class_slip(
    db: AsyncSession, session_id, student_id, index: int
) -> tuple[str | None, int]:
    """The latest misconception other students showed on this step, and how many of them."""
    rows = (
        await db.execute(
            select(EvidenceRecord.student_id, EvidenceRecord.payload)
            .where(
                EvidenceRecord.session_id == session_id,
                EvidenceRecord.student_id != student_id,
                EvidenceRecord.kind == EvidenceKind.SIGNAL.value,
                EvidenceRecord.payload["signal"].as_string() == SignalKind.MISCONCEPTION.value,
                EvidenceRecord.payload["step_index"].as_integer() == index,
            )
            .order_by(EvidenceRecord.created_at.desc())
        )
    ).all()
    if not rows:
        return None, 0
    note = str(rows[0][1].get("note") or "")[:160]
    return note or None, len({r[0] for r in rows})


def _now_line(
    *, teacher_asks: str | None, state: LearningState, history: list, intent: str | None
) -> tuple[str, str | None]:
    """The one line on what this turn is, and the button words if a button was pressed."""
    if teacher_asks:
        return (
            f'Your teacher has just asked this about this student: "{teacher_asks}". Write to '
            "the student now and do what they asked. For this reply the teacher's words come "
            "before the rules above: if they say to move the student on, set step_done and ask "
            "the next step's first question even without a met answer; if they say to give the "
            "answer, give it. Do nothing they did not ask for. If it is about something other "
            "than the work (a break, their laptop, how they are behaving), say it kindly and "
            "plainly."
            + ("" if history else " They have not opened the lesson yet: greet them first."),
            None,
        )
    if state.status == LearningStatus.COMPLETED.value:
        return (
            "The student has finished the lesson. Answer them kindly and briefly; set no task "
            "and no assessment, and don't start new work.",
            None,
        )
    if not history:
        return "The student has just opened the lesson. Greet them and begin step 1.", None
    if intent:
        return f"They pressed a help button: {intent}", intent
    return "Carry on from what they just wrote.", None


async def student_context(
    db: AsyncSession,
    *,
    session: Session,
    contract: LessonContract,
    student: User,
    conversation: Conversation,
    state: LearningState,
    intent: str | None = None,
    condition: dict | None = None,
    rung: str | None = None,
    attempts: int | None = None,
    teacher_asks: str | None = None,
    example_button: bool = False,
) -> Context:
    brief = LessonBrief.model_validate(contract.brief or {})
    index = state.step_index
    step = brief.steps[index] if index < len(brief.steps) else None
    # Counting this message, when it is an attempt: what the checks will hold the reply to.
    count = state.attempts_on_step if attempts is None else attempts
    # What the teacher has just asked for this student can include the answer itself.
    allowed = Disclosure.FULL if teacher_asks else brief.rules.allowed_disclosure(count)
    if (
        example_button
        and brief.rules.hints_allowed
        and DISCLOSURE_ORDER.index(allowed) < DISCLOSURE_ORDER.index(Disclosure.PARTIAL)
    ):
        # What the button promises: a worked example of a different problem, never theirs.
        allowed = Disclosure.PARTIAL

    # Only this student's conversation, and only what they could see.
    history = [
        m
        for m in await store.messages(db, conversation.id, limit=CONVERSATION_WINDOW)
        if m.role in (MessageRole.STUDENT.value, MessageRole.AGENT.value)
        and m.audience == Audience.ALL.value
    ]
    guidance = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.student_id == student.id,
                EvidenceRecord.kind == EvidenceKind.TEACHER_GUIDANCE.value,
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()
    recalled = await memory.retrieve(
        db, student_id=student.id, topics=brief.topics, exclude_session_id=session.id
    )
    # In a study the assigned condition decides, not the lesson's tick-box.
    condition = condition or {}
    # Always on: the agent starts from what this student's own records show. Only a study
    # turns it off, for the arm it is compared against.
    personalise = condition.get("memory", True)
    use_recalled = personalise and bool(recalled)
    known = []
    if personalise:
        known = await memory.knowledge(db, student_id=student.id, exclude_session_id=session.id)
    guidance_texts = [g.payload.get("text", "") for g in guidance]
    now_line, button = _now_line(
        teacher_asks=teacher_asks, state=state, history=history, intent=intent
    )

    chosen = prompt_set()
    if chosen == "v8":
        system = prompt_v8.system_v8(
            brief=brief,
            allowed=allowed,
            state=state,
            step=step,
            count=count,
            guidance_texts=guidance_texts,
            recalled=recalled,
            known=known,
            use_recalled=use_recalled,
            now_line=now_line,
            teacher_asks=teacher_asks,
            history=history,
            example_button=example_button,
            intent=intent,
        )
    else:
        noticed = await _noticed(
            db,
            session=session,
            student=student,
            brief=brief,
            state=state,
            index=index,
            count=count,
            history=history,
            recalled=[r.summary for r in recalled] if use_recalled else [],
            known=known,
        )
        task = None
        if 0 <= index < len(state.steps or []):
            task = (state.steps[index] or {}).get("task")
        system = scaffold.assemble(
            brief=brief,
            index=index,
            task=task,
            attempts=count,
            allowed=allowed,
            guidance=guidance_texts,
            noticed=noticed,
            now=now_line,
            example_button=example_button and brief.rules.hints_allowed,
            depth=chosen == "v10",
        )
    if contract.approach:
        system += "\n\n" + approaches.teaching(contract.approach)
    if rung is not None:
        system += (
            "\n\nHelp ladder (fixed for this lesson, and checked): " + " -> ".join(LADDER) + ". "
            f"The only form of help you may give on this turn is {rung}: {RUNG_WORDS[rung]}. "
            'Name it in "rung". When their answer meets the criteria no help is needed: '
            'judge it, move on, and leave "rung" null.'
        )
    if chosen != "v8":
        # The same position as data, compact: the scripted demo responder reads it, and a
        # model can check itself against it.
        system += (
            "\n\n"
            + prompt_v8.DATA_LABEL
            + json.dumps(_position(brief, state, step, count, now_line, button, guidance_texts))
        )

    messages = [
        {
            "role": "user" if m.role == MessageRole.STUDENT.value else "assistant",
            "content": m.text,
        }
        for m in history
    ]
    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": "(The student is waiting for you.)"})

    manifest = {
        "mode": "student",
        "prompt_set": chosen,
        "session_id": str(session.id),
        "student_id": str(student.id),
        "conversation_id": str(conversation.id),
        "message_ids": [str(m.id) for m in history],
        "guidance_ids": [str(g.id) for g in guidance],
        "retrieved_ids": [str(r.record_id) for r in recalled],
        "retrieved_used": use_recalled,
        "condition": condition,
        "rung_permitted": rung,
        "knowledge_evidence_ids": [i for t in known for i in t["evidence_ids"]],
        "step_index": state.step_index,
        "allowed_disclosure": allowed.value,
        "target_dok": step.depth if step and chosen == "v10" else None,
        "approach": contract.approach,
        "approach_version": approaches.VERSION if contract.approach else None,
    }
    return Context(system=system, messages=messages, manifest=manifest)


async def _noticed(
    db, *, session, student, brief, state, index, count, history, recalled, known
) -> scaffold.Noticed:
    on_step = (state.steps or [{}])[index] if index < len(state.steps or []) else {}
    on_step = on_step or {}
    streak, gap = _bare_streak(history)
    now = datetime.now(UTC)
    minutes_in = int((now - history[0].created_at).total_seconds() // 60) if history else None
    closes_in = None
    if session.closes_at is not None:
        left = (session.closes_at - now).total_seconds() / 60
        if 0 < left <= 180:
            closes_in = int(left)
    slip, slip_count = await _class_slip(db, session.id, student.id, index)
    return scaffold.Noticed(
        attempts=count,
        hints=int(on_step.get("hints", 0)),
        examples=int(on_step.get("examples", 0)),
        worked=int(on_step.get("worked", 0)),
        bare_streak=streak,
        bare_gap_seconds=gap,
        minutes_in=minutes_in,
        planned_minutes=brief.duration_minutes,
        steps_after=max(0, len(brief.steps) - index - 1),
        closes_in_minutes=closes_in,
        asked_teacher_open=await _asked_teacher_open(db, session.id, student.id),
        depth_asks=int(on_step.get("depth_asks", 0)),
        class_slip=slip,
        class_slip_count=slip_count,
        recalled=recalled,
        known=[{k: t[k] for k in ("topic", "judged", "met", "misconceptions")} for t in known],
    )


def _position(brief, state, step, count, now_line, button, guidance_texts) -> dict:
    """Where the student is, as data. No reference answers: the sentence block holds the
    current step's, and a later step's is never sent."""
    strip = {"reference_answer"}
    data = {
        "where_the_student_is": {
            "step_number": state.step_index + 1,
            "step_count": len(brief.steps),
            "step": step.model_dump(mode="json", exclude=strip) if step else None,
            "status": state.status,
            "answers_on_this_step": count,
            "steps_so_far": state.steps,
        },
        "lesson_brief": {
            "title": brief.title,
            "steps": [s.model_dump(mode="json", exclude=strip) for s in brief.steps],
        },
        "teacher_guidance_for_this_student": guidance_texts,
    }
    if now_line.startswith(
        ("The student has just opened", "Your teacher", "The student has finished")
    ):
        data["now"] = now_line
    if button:
        data["student_used_button"] = button
    return data
