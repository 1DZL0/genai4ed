"""Closing sessions whose time is up. There is no timer: every path that reads a session
closes it first if its deadline has passed, and `closed_at` records the deadline itself."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import SessionStatus
from app.models import Session


async def close_expired(db: AsyncSession, session_id: uuid.UUID | None = None) -> None:
    """Close every session past its deadline, or just `session_id`."""
    stmt = (
        update(Session)
        .where(
            # A scheduled lesson has no deadline until it starts.
            Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            Session.closes_at <= datetime.now(UTC),
        )
        .values(status=SessionStatus.CLOSED.value, closed_at=Session.closes_at)
        .execution_options(synchronize_session="fetch")
    )
    if session_id is not None:
        stmt = stmt.where(Session.id == session_id)

    result = await db.execute(stmt)
    if result.rowcount:
        await db.commit()
