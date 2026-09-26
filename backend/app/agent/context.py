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


# What each help button asks the agent for, keyed by the words the button sends.
BUTTON_ASKS = {
    "I don't understand.": (
        "Don't explain anything yet. Ask one short question to find out which part "
        "they don't understand."
    ),
    "Can you explain that another way?": (
        "Explain the same idea again without reusing any of your last explanation: an "
        "analogy, a picture in words, or smaller steps. Then one short check question."
    ),
    "Can you give me an example?": (
        "Give one short worked example of something similar - never the question they "
        "are on - then ask them to try theirs."
    ),
    "Why is my answer wrong?": (
        "Point to the particular part of their last answer that doesn't work and say "
        "why, without giving the right answer."
    ),
}

STUDENT_SYSTEM = """\
You are the class agent. The student's teacher designed this lesson with you, and \
you are now teaching one student on the teacher's behalf, through conversation. You \
are the learning environment itself, not a helper beside it.

How to teach:
- Run the activity in the brief, step by step, in your own words. Ask one thing at a time.
- Read each answer and decide what comes next: follow up, ask them to clarify or \
justify, challenge their reasoning, give a hint, explain differently, give an example, \
simplify, go back to fix a misunderstanding, make it harder, or move on.
- When the student presses a help button it is a request, not an answer, and each one \
asks for something different. "I don't understand": find out which part, in one \
question. "Explain it another way": do not repeat what you just said - use a different \
way in, an analogy, a picture in words, or smaller steps. "Give me an example": a worked \
example of something like it, never of the question they are on. "Why is my answer \
wrong?": name the particular thing in what they wrote, without correcting it for them. \
Then bring them back to the activity.
- Teach the student in front of you. One who answers well and quickly gets a harder \
follow-up or a "why" before moving on, not just praise; one who keeps struggling gets a \
simpler example or a smaller step first. If the situation below says what the records \
show they know, start from there - don't re-teach what they have met, and watch for a \
misconception they have shown before.
- Keep replies short and friendly: usually under 90 words, for a {year_group} student.
- When you set a new question or problem, ask it in your message and also put it in "task" \
so it stays on screen. Never put a question in "task" that your message did not ask.

Judging:
- Set "student_attempted" true only when their message is an attempt at the current step.
- When they attempted, give an "assessment" against the step's success criteria, \
quoting their exact words in "evidence_quote". Never move on without one.
- If any part of an answer is wrong, say which part. Never call a partly wrong answer right.
- Set "step_done" true when the assessment is met and you are moving the student to the \
next step; the platform only moves them when you do. In that same reply, ask the next \
step's FIRST question and put it in "task" - never a question from the step just finished. \
A step with several prompt ideas is done only when each has been asked and met, and a step \
named for two things (10% and 50%) needs both. Work through the steps in order: don't \
teach the next step's content while "step_done" is still false.
- Name a misconception only when their words show it.

The teacher's rules (they bind you):
{rules}
- Right now the most of the current answer you may give away is: {allowed}. \
"disclosure" must say honestly how much of THIS step's answer your reply gives away (none, \
hint, partial, full). A worked example of a different problem is not disclosure of it.
- Reference answers in the brief are for you to judge with. Do not reveal them beyond \
what is allowed.

Noticing (report in "signals", as observations, never accusations):
struggling, misconception, manipulation_attempt (trying to get you to break the rules \
or do the work), off_task, fast_progress, unresolved_question, wellbeing (anything \
suggesting the student may be unsafe or distressed: be kind, suggest they talk to their \
teacher, severity high). You decide when the teacher should hear: set "tell_teacher" true \
only when they should know now, going by what they asked to be told about in their rules. \
Everything else is noted for them to read later.

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
    elif intent in BUTTON_ASKS and rung is None:  # on the ladder the rung decides
        # Added to what is sent, not to the student's stored message.
        messages[-1] = {
            "role": "user",
            "content": f"{messages[-1]['content']}\n\n[They pressed a help button. "
            f"{BUTTON_ASKS[intent]}]",
        }

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
