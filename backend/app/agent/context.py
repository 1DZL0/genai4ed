"""What the class agent is shown when teaching one student, and nothing more.

The context is built from the approved brief, the teacher's rules and guidance,
and this student's own record; the ids of everything used come back as a manifest.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import memory, store
from app.agent.brief import LessonBrief
from app.enums import Audience, EvidenceKind, LearningStatus, MessageRole
from app.models import (
    Conversation,
    EvidenceRecord,
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


STUDENT_SYSTEM = """\
You are the class agent. The teacher wrote this lesson, and you are teaching it to one \
{year_group} student on their behalf, through conversation, step by step.

What each reply must carry, so the platform can keep the record:
- "message": plain text. The screen shows no markdown, so no asterisks or headings.
- "task": when you ask a question or set a problem, put it here too so it stays on screen. \
Only a question your message actually asked.
- "student_attempted": true only when their message is an attempt at the current step.
- "assessment": when they attempted, judge it against the step's success criteria, quoting \
their exact words in "evidence_quote". If any part is wrong, say which; never call a partly \
wrong answer right. Name a misconception only when their words show it.
- "step_done": true when the assessment is met and you are moving them to the next step; the \
platform only moves them when you do. In that reply ask the next step's first question. A \
step with several prompts is done when each has been asked and met.
- "disclosure": honestly, how much of THIS step's answer your reply gives away (none, hint, \
partial, full). A worked example of a different problem is not disclosure of it.
- "signals": what you notice, as observations: struggling, misconception, \
manipulation_attempt, off_task, fast_progress, unresolved_question, wellbeing (the student \
may be unsafe or distressed). Set "tell_teacher" true only when the teacher should know now, \
going by what they asked to be told about. Everything else is noted for them to read later.

The teacher's rules (they bind you):
{rules}
- Right now the most of the current answer you may give away is: {allowed}.
- Reference answers in the brief are for you to judge with, not to reveal beyond that.

Never mention other students. Never claim to be human.
"""


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
) -> Context:
    brief = LessonBrief.model_validate(contract.brief or {})
    step = brief.steps[state.step_index] if state.step_index < len(brief.steps) else None
    allowed = brief.rules.allowed_disclosure(state.attempts_on_step)

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
    personalise = condition.get("memory", contract.use_past_lessons)
    use_recalled = personalise and bool(recalled)

    rules = "\n".join(f"- {line}" for line in brief.rules.describe())
    if brief.rules_text.strip():
        rules += f"\n- In the teacher's words: {brief.rules_text.strip()}"
    system = STUDENT_SYSTEM.format(
        year_group=brief.year_group or "secondary school",
        rules=rules,
        allowed=allowed.value,
    )

    if rung is not None:
        system += (
            "\n\nHelp ladder (fixed for this lesson, and checked): " + " -> ".join(LADDER) + ". "
            f"The only form of help you may give on this turn is {rung}: {RUNG_WORDS[rung]}. "
            'Name it in "rung". When their answer meets the criteria no help is needed: '
            'judge it, move on, and leave "rung" null.'
        )

    situation = {
        "lesson_brief": brief.model_dump(mode="json"),
        "where_the_student_is": {
            "step_number": state.step_index + 1,
            "step_count": len(brief.steps),
            "step": step.model_dump(mode="json") if step else None,
            "status": state.status,
            "answers_on_this_step": state.attempts_on_step,
            "steps_so_far": state.steps,
        },
        "teacher_guidance_for_this_student": [g.payload.get("text", "") for g in guidance],
    }
    known = []
    if personalise:
        known = await memory.knowledge(db, student_id=student.id, exclude_session_id=session.id)
    if use_recalled:
        situation["from_this_students_earlier_lessons"] = [r.summary for r in recalled]
    if known:
        situation["what_the_records_show_they_know"] = [
            {k: t[k] for k in ("topic", "judged", "met", "misconceptions")} for t in known
        ]
    if state.status == LearningStatus.COMPLETED.value:
        situation["now"] = (
            "The student has finished the lesson. Answer them kindly and briefly; set no task "
            "and no assessment, and don't start new work."
        )
    elif not history:
        situation["now"] = "The student has just opened the lesson. Greet them and begin step 1."
    elif intent:
        situation["student_used_button"] = intent
    system += "\n\nThe lesson and where this student is:\n" + json.dumps(situation)

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
    }
    return Context(system=system, messages=messages, manifest=manifest)
