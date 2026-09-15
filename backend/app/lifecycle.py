"""When a session ends.

A session is a timed activation, so `closes_at` is a limit, not a suggestion.
Rather than a background timer - one more process to keep alive - expiry is
settled lazily: every path that reads a session first closes it if its time
is up. The database therefore never shows a session as open past its deadline
to anyone who asks, and `closed_at` records the deadline itself rather than the
moment someone happened to look.
"""

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
            Session.status != SessionStatus.CLOSED.value,
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
