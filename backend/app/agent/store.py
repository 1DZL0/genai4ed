"""Conversations and messages with the class agent."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Audience, ConversationKind, MessageRole, RetentionClass
from app.ledger import purge_after
from app.models import Conversation, Message

# A teacher's thread is part of the lesson record; student chat expires sooner.
RETENTION: dict[ConversationKind, RetentionClass] = {
    ConversationKind.TEACHER: RetentionClass.SUBMITTED_WORK,
    ConversationKind.STUDENT: RetentionClass.EXPLORATORY_CHAT,
}


async def teacher_thread(db: AsyncSession, *, teacher_id: uuid.UUID) -> Conversation:
    """The teacher's one conversation with the class agent, created on first use."""
    found = await db.scalar(
        select(Conversation).where(
            Conversation.kind == ConversationKind.TEACHER.value,
            Conversation.teacher_id == teacher_id,
        )
    )
    if found is None:
        found = Conversation(kind=ConversationKind.TEACHER.value, teacher_id=teacher_id)
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
        # Stamped here: Postgres now() is per transaction, and a turn writes several messages.
        created_at=datetime.now(UTC),
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
