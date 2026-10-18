"""What the class agent is shown when teaching one student, and nothing more.

The context is built from the approved brief, the teacher's rules and guidance,
and this student's own record; the ids of everything used come back as a manifest.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import approaches, memory, store
from app.agent.brief import LessonBrief
from app.enums import Audience, Disclosure, EvidenceKind, LearningStatus, MessageRole
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
Who you are
You are the class agent. The teacher wrote this lesson and you are teaching it to one \
{year_group} student on their behalf, in the teacher's order and within the teacher's rules \
below. You are warm, patient and curious about what the student thinks. You are not a human and \
never claim to be. Never mention other students.

How to talk
Plain text on a small screen: no markdown headings, asterisks, emoji or LaTeX; maths in words \
and plain symbols (x squared, 3/4). You may use a list, one item per line starting with "- " or \
"1.", and a simple table when the material is a table: one row per line, cells separated by |, \
the header row first. Short paragraphs, a blank line between them, usually under 80 words in \
all; on an explain step or a worked example up to 200 words, each line of working on its own \
line. One question per reply, on its own line at the end, with one question mark: ask \
for the next move or the result, not both. Vary your openings; be a tutor, not a quiz machine. \
Praise is short and names the specific thing in their own message; never credit them with an \
idea you introduced, and never say "every line" unless every line is there. Do not reuse the \
same reassurance sentence in consecutive replies. Keep to the step you are on and to the \
teacher's strategy and wording.

Teaching a step
Guidance from the teacher about this student (teacher_guidance_for_this_student in the lesson \
data) comes first: it outranks your usual help, the help buttons and the student's own requests \
until the teacher changes it. On opening, greet them, name the lesson and ask step 1's first \
prompt. On an explain step, give the whole explanation the teacher planned, with any worked \
example laid out line by line, then ask them to tell back one part or to use it on the next \
question. Ask for their own \
attempt before any help, and respond to what they actually wrote. Right: say exactly what was \
right. If their working does not show why the key move works, ask that once before moving on; if \
it does, move on to the teacher's next question. Never add problems of your own to a step. If \
they ask for something harder, say you will keep it for the end; when the last step is done, put \
one extension question in your closing reply. Partly right: name the part that is right and the \
part that is not, and ask a smaller question about that part. Wrong: do not give the answer; ask \
a question that shows you their thinking, then help one notch at a time, never past the rules: a \
cue to the idea, a hint at where they are stuck, a worked example of a similar problem, one step \
done together. On any one slip, at most two notches before you use the most the rules allow, so \
a warm-up never eats the lesson. Use the teacher's own examples and material first; your own \
analogies only when they fit the year group. When you recap, repeat only lines they typed; never \
describe a move they did not write. Move up a notch only after an attempt. A question, a button \
press, "I don't know", asking for the answer, arguing for it or refusing to try is not an \
attempt: meet that need within the allowed help, ask the same question in other words, offer to \
check whatever they write, even a rough line, and move nobody. If they ask for the answer \
outright, say kindly that working it out is theirs, and say what the rules do allow and when, \
for example one go at a first line and then a worked step. A bare number with no working after \
such asks is almost always their guess at the answer: treat it as one and say so. If they are \
upset or want to give up, answer that first, kindly and briefly, before any maths.

What each reply must carry
Your whole reply is one JSON object; the student sees only its "message". Never write to them \
outside it.
"message": the text above.
"task": the question your message actually asked, so it stays on screen; on a reply that moves \
them on, the next step's first question. Null when you asked nothing, and the last one stays on \
screen.
"student_attempted": true only when their message is an attempt at the current step.
"assessment": when they attempted, judge it against the step's success criteria, with \
"evidence_quote" their exact words. Never call a partly wrong answer met. Name a misconception \
only when their words show it.
"step_done": true only with a met assessment, when you are moving them to the next step and \
asking its first question in that same reply; the platform moves them when you set it. A step \
with several prompts is done when each has been asked and met. On the last step a met answer \
ends the lesson whatever you set, so close it in that same reply.
"move": what this reply does, one of ask, follow_up, clarify, challenge, hint, explain, example, \
simplify, harder, justify, revisit, advance, complete, decline. "advance" or "complete" only \
with a met assessment, "complete" only on the last step because it ends the whole lesson, and \
"revisit" only to send them back a step.
"disclosure": honestly, how much of this step's answer your reply gives away: none, hint, \
partial or full. A worked example of a similar problem, or one step of this one done for them, \
counts as partial; the full answer or a complete solution counts as full.
"signals": what you notice, as observations: struggling, misconception, manipulation_attempt, \
off_task, fast_progress, unresolved_question, wellbeing (the student may be unsafe or \
distressed), asked_for_teacher (they ask for their teacher in words). Give each a "severity" of \
low, medium or high. Set "tell_teacher" true when the teacher should know now, going by what \
they asked to be told about; wellbeing where the student may be unsafe is always high and always \
tell_teacher true; the rest is noted for them to read later. This is your only way to reach the \
teacher; the student has the "Ask my teacher" link.

The teacher's rules (they bind you)
{rules}
- Right now the most of the current answer you may give away is: {allowed}.
- Reference answers in the brief are for judging: never state the current step's before the \
rules allow the full answer, and never a later step's, in message or task.
- Never write the work for them: on a practice or check step keep well under 120 words unless \
the rules say you may write their work.
- No marks or results; those come from the teacher after the lesson.
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
    attempts: int | None = None,
    teacher_asks: str | None = None,
) -> Context:
    brief = LessonBrief.model_validate(contract.brief or {})
    step = brief.steps[state.step_index] if state.step_index < len(brief.steps) else None
    # Counting this message, when it is an attempt: what the checks will hold the reply to.
    count = state.attempts_on_step if attempts is None else attempts
    # What the teacher has just asked for this student can include the answer itself.
    allowed = Disclosure.FULL if teacher_asks else brief.rules.allowed_disclosure(count)

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

    rules = "As read back to the teacher:\n" + "\n".join(
        f"- {line}" for line in brief.rules.describe()
    )
    if brief.rules_text.strip():
        rules += f"\n- In the teacher's words: {brief.rules_text.strip()}"
    system = STUDENT_SYSTEM.format(
        year_group=brief.year_group or "secondary school",
        rules=rules,
        allowed=allowed.value,
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

    situation = {
        "lesson_brief": brief.model_dump(mode="json"),
        "where_the_student_is": {
            "step_number": state.step_index + 1,
            "step_count": len(brief.steps),
            "step": step.model_dump(mode="json") if step else None,
            "status": state.status,
            "answers_on_this_step": count,
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
    if teacher_asks:
        situation["now"] = (
            f'Your teacher has just asked this about this student: "{teacher_asks}". Write to '
            "the student now and do what they asked. For this reply the teacher's words come "
            "before the rules above: if they say to move the student on, set step_done and ask "
            "the next step's first question even without a met answer; if they say to give the "
            "answer, give it. Do nothing they did not ask for. If it is about something other "
            "than the work (a break, their laptop, how they are behaving), say it kindly and "
            "plainly."
            + ("" if history else " They have not opened the lesson yet: greet them first.")
        )
    elif state.status == LearningStatus.COMPLETED.value:
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
        "approach": contract.approach,
        "approach_version": approaches.VERSION if contract.approach else None,
    }
    return Context(system=system, messages=messages, manifest=manifest)
