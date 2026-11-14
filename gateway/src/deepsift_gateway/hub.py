"""Fan-out of live messages to the WebSocket clients watching an investigation."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

QUEUE_SIZE = 1000


class Hub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = defaultdict(set)

    def publish(self, investigation_id: str, message: dict[str, Any]) -> None:
        """Hand a message to every subscriber. A client too slow to keep up is dropped."""
        for queue in list(self._subscribers.get(investigation_id, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self._subscribers[investigation_id].discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)  # tells the reader it fell behind

    @asynccontextmanager
    async def subscribe(
        self, investigation_id: str
    ) -> AsyncIterator[asyncio.Queue[dict[str, Any] | None]]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(QUEUE_SIZE)
        self._subscribers[investigation_id].add(queue)
        try:
            yield queue
        finally:
            subscribers = self._subscribers.get(investigation_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    del self._subscribers[investigation_id]

    def count(self, investigation_id: str) -> int:
        return len(self._subscribers.get(investigation_id, ()))
