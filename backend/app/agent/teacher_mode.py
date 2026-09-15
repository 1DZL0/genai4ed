"""The class agent working with the teacher.

Designing: the teacher describes what they want and hands over material; the
agent redrafts the lesson brief each turn and says what it changed and what it
still needs to know. The teacher directs; they never fill in a form.

Classroom and review turns (asking the agent about a lesson, its summary of
the class) are built on the same pattern in later modules.
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import store
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, LLMError, ask_structured, image_part
from app.enums import (
    ConversationKind,
    LeakageCheck,
    MessageRole,
    ValidationOutcome,
)
from app.models import AgentTurn, LessonContract, Material, Message, User

PROMPT_VERSION = "design-turn-v1"
POLICY_VERSION = "class-agent-v1"
DESIGN_WINDOW = 30
MATERIAL_CHARS = 24_000

DESIGN_SYSTEM = """\
You are the class agent, working with a teacher to design a lesson you will then \
teach to each of their students, one to one, through conversation.

Each turn, read what the teacher said and the materials they gave, and return the \
whole lesson brief as it should now be ("brief"), or null if nothing should change. \
In "reply", say briefly what you changed and ask at most two questions about what \
is still unclear. Write like a helpful colleague, not a form.

Shaping the brief:
- Objectives: what students should understand or be able to do, in plain words.
- Steps: a short activity the agent can run conversationally, sized to the time. Mix \
kinds: explain, question, practice, check. Each step has a goal, a few prompt ideas \
and success criteria the agent can judge answers against. Give a reference answer \
where one exists (students never see it).
- Strategy: how to teach it - level, order, tone, what to emphasise, how to use prior \
knowledge.
- Assessment: a few criteria with points, if the teacher wants the work judged.
- Topics: 1-4 short lowercase tags for the subject matter.

Rules: when the teacher describes how the agent should behave, keep their words in \
"rules_text" and compile them into "rules":
- hints_allowed; partial_after_attempts (worked steps only after this many answers); \
full_answer_after_attempts (null = never give the final answer); may_write_for_student;
- escalations: [{signal, after, action}] for what should be logged, summarised or \
shown to the teacher straight away. Signals: struggling, misconception, \
manipulation_attempt, off_task, fast_progress, unresolved_question, wellbeing, \
asked_for_teacher. Actions: log, summarise, alert.
- notes: anything else, in the teacher's words.
If a rule is ambiguous, pick the safer reading and ask.

Use only the teacher's materials and ordinary subject knowledge suitable for school. \
Keep the existing brief unless the teacher asks for a change.
"""


class DesignTurnOut(BaseModel):
    reply: str = Field(min_length=1, max_length=3000)
    brief: LessonBrief | None = None
    open_questions: list[str] = Field(default_factory=list, max_length=4)


class DesignUnavailable(Exception):
    pass


async def _materials(db: AsyncSession, plan_id: uuid.UUID) -> list[Material]:
    return list(
        (
            await db.scalars(
                select(Material).where(Material.plan_id == plan_id).order_by(Material.created_at)
            )
        ).all()
    )


async def design_turn(
    db: AsyncSession,
    client: LLMClient,
    *,
    contract: LessonContract,
    teacher: User,
    text: str,
    material_ids: list[uuid.UUID],
) -> Message:
    conversation = await store.design_conversation(
        db, teacher_id=teacher.id, plan_id=contract.plan_id
    )
    await store.add_message(
        db,
        conversation,
        role=MessageRole.TEACHER,
        text=text,
        material_ids=[str(m) for m in material_ids],
    )

    brief = LessonBrief.model_validate(contract.brief or {})
    materials = await _materials(db, contract.plan_id)
    budget = MATERIAL_CHARS
    material_text: list[dict] = []
    for m in materials:
        if m.extracted_text and budget > 0:
            excerpt = m.extracted_text[:budget]
            budget -= len(excerpt)
            material_text.append({"file": m.filename, "text": excerpt})
    system = (
        DESIGN_SYSTEM
        + "\n\nThe brief so far:\n"
        + brief.model_dump_json()
        + (
            "\n\nThe teacher's materials:\n"
            + "\n\n".join(f"--- {t['file']} ---\n{t['text']}" for t in material_text)
            if material_text
            else ""
        )
        + f"\n\nStill needed before approval: {', '.join(brief.missing()) or 'nothing'}."
    )

    history = [
        m
        for m in await store.messages(db, conversation.id, limit=DESIGN_WINDOW)
        if m.role in (MessageRole.TEACHER.value, MessageRole.AGENT.value)
    ]
    messages: list[dict] = []
    images = {str(m.id): m for m in materials if m.media_type.startswith("image/")}
    for m in history:
        role = "user" if m.role == MessageRole.TEACHER.value else "assistant"
        attached = [images[i] for i in m.material_ids if i in images] if role == "user" else []
        if attached:
            messages.append(
                {
                    "role": role,
                    "content": [
                        {"type": "text", "text": m.text},
                        *[image_part(a.media_type, a.content) for a in attached],
                    ],
                }
            )
        else:
            messages.append({"role": role, "content": m.text})

    manifest = {
        "mode": "design",
        "plan_id": str(contract.plan_id),
        "message_ids": [str(m.id) for m in history],
        "material_ids": [str(m.id) for m in materials],
    }
    try:
        out, result, tries = await ask_structured(
            client,
            DesignTurnOut,
            purpose="lesson_design",
            system=system,
            messages=messages,
            max_tokens=4000,
        )
    except LLMError as exc:
        db.add(
            AgentTurn(
                conversation_id=conversation.id,
                mode=ConversationKind.DESIGN.value,
                context_manifest=manifest,
                policy_version=POLICY_VERSION,
                prompt_version=PROMPT_VERSION,
                provider=client.name,
                model=client.model,
                latency_ms=0,
                validation_outcome=ValidationOutcome.WITHHELD.value,
                leakage_check=LeakageCheck.SKIPPED.value,
                conflicts=["malformed_output"],
                request={"text": text},
                response={"error": str(exc)[:500]},
            )
        )
        await db.commit()
        raise DesignUnavailable(str(exc)) from exc

    turn = AgentTurn(
        conversation_id=conversation.id,
        mode=ConversationKind.DESIGN.value,
        context_manifest=manifest,
        policy_version=POLICY_VERSION,
        prompt_version=PROMPT_VERSION,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        validation_outcome=(
            ValidationOutcome.REGENERATED if tries > 1 else ValidationOutcome.OK
        ).value,
        leakage_check=LeakageCheck.SKIPPED.value,
        conflicts=[],
        request={"text": text, "material_ids": [str(m) for m in material_ids]},
        response={"raw": result.raw[:12000]},
    )
    db.add(turn)
    await db.flush()

    changed = out.brief is not None
    if out.brief is not None:
        contract.brief = out.brief.model_dump(mode="json")
        if out.brief.title.strip():
            contract.title = out.brief.title.strip()[:255]
        if out.brief.subject.strip():
            contract.subject = out.brief.subject.strip()[:64]
        brief = out.brief
    reply = await store.add_message(
        db,
        conversation,
        role=MessageRole.AGENT,
        text=out.reply,
        data={
            "brief_changed": changed,
            "open_questions": out.open_questions,
            "missing": brief.missing(),
        },
        turn_id=turn.id,
    )
    await db.commit()
    return reply
