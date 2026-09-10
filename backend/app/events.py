"""In-process event broker behind the teacher's live view.

A class is 25-30 students in one room, so a queue per subscriber inside one
process is genuinely sufficient - the note says so explicitly, and offers
polling as an equally acceptable option.

This is the realtime seam. If a second worker process ever exists, `publish`
becomes a Postgres NOTIFY or a Redis publish and nothing else changes.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

QUEUE_SIZE = 128


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue]] = {}

    @asynccontextmanager
    async def subscribe(self, session_id: uuid.UUID) -> AsyncIterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.setdefault(session_id, set()).add(queue)
        try:
            yield queue
        finally:
            listeners = self._subscribers.get(session_id, set())
            listeners.discard(queue)
            if not listeners:
                self._subscribers.pop(session_id, None)

    async def publish(self, session_id: uuid.UUID, event: dict) -> None:
        for queue in list(self._subscribers.get(session_id, set())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A console that has stopped reading must never block a lesson.
                pass

    def subscriber_count(self, session_id: uuid.UUID) -> int:
        return len(self._subscribers.get(session_id, set()))


broker = EventBroker()
