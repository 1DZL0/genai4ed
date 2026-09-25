"""In-process event queues behind the teacher's live view. One process serves a class, so
this is enough; a second worker would swap `publish` for Postgres NOTIFY or Redis."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue]] = {}

    @asynccontextmanager
    async def subscribe(self, session_id: uuid.UUID) -> AsyncIterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
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
                pass  # a console that stopped reading must never block a lesson


broker = EventBroker()
