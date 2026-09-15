"""Conversations and messages with the class agent."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Audience, ConversationKind, MessageRole, RetentionClass
from app.ledger import purge_after
from app.models import Conversation, Message

# What a teacher says while designing a lesson is part of the lesson's record.
# What a student and the agent say to each other is chat, and expires sooner;
# the judgments and signals drawn from it are kept in the evidence ledger.
RETENTION: dict[ConversationKind, RetentionClass] = {
    ConversationKind.DESIGN: RetentionClass.SUBMITTED_WORK,
    ConversationKind.CLASSROOM: RetentionClass.SUBMITTED_WORK,
    ConversationKind.STUDENT: RetentionClass.EXPLORATORY_CHAT,
}


async def design_conversation(db: AsyncSession, *, teacher_id: uuid.UUID, plan_id: uuid.UUID):
    found = await db.scalar(
        select(Conversation).where(
            Conversation.kind == ConversationKind.DESIGN.value, Conversation.plan_id == plan_id
        )
    )
    if found is None:
        found = Conversation(
            kind=ConversationKind.DESIGN.value, teacher_id=teacher_id, plan_id=plan_id
        )
        db.add(found)
        await db.flush()
    return found


async def classroom_conversation(
    db: AsyncSession, *, teacher_id: uuid.UUID, session_id: uuid.UUID
) -> Conversation:
    found = await db.scalar(
        select(Conversation).where(
            Conversation.kind == ConversationKind.CLASSROOM.value,
            Conversation.session_id == session_id,
        )
    )
    if found is None:
        found = Conversation(
            kind=ConversationKind.CLASSROOM.value, teacher_id=teacher_id, session_id=session_id
        )
        db.add(found)
        await db.flush()
    return found


async def student_conversation(
    db: AsyncSession, *, session_id: uuid.UUID, student_id: uuid.UUID
) -> Conversation:
    found = await db.scalar(
        select(Conversation).where(
            Conversation.kind == ConversationKind.STUDENT.value,
            Conversation.session_id == session_id,
            Conversation.student_id == student_id,
        )
    )
    if found is None:
        found = Conversation(
            kind=ConversationKind.STUDENT.value, session_id=session_id, student_id=student_id
        )
        db.add(found)
        await db.flush()
    return found


async def add_message(
    db: AsyncSession,
    conversation: Conversation,
    *,
    role: MessageRole,
    text: str,
    data: dict | None = None,
    audience: Audience = Audience.ALL,
    material_ids: list[str] | None = None,
    turn_id: uuid.UUID | None = None,
) -> Message:
    retention = RETENTION[ConversationKind(conversation.kind)]
    message = Message(
        conversation_id=conversation.id,
        role=role.value,
        text=text,
        data=data or {},
        audience=audience.value,
        material_ids=material_ids or [],
        turn_id=turn_id,
        retention_class=retention.value,
        purge_after=purge_after(retention),
    )
    db.add(message)
    await db.flush()
    return message


async def messages(
    db: AsyncSession, conversation_id: uuid.UUID, *, limit: int | None = None
) -> list[Message]:
    """Oldest first. With `limit`, the most recent `limit` messages."""
    query = select(Message).where(Message.conversation_id == conversation_id)
    if limit is None:
        return list((await db.scalars(query.order_by(Message.created_at, Message.id))).all())
    recent = (
        await db.scalars(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit))
    ).all()
    return list(reversed(recent))
