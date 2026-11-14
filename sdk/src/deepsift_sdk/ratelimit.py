"""Pace a service that acts through the user's own account (contract section 3).

Two rules: a minimum gap between operations, and a cap per UTC day. State lives in a
JSON file, guarded by a file lock, so several processes on one machine (the CLI and a
worker) share one budget. Each call reserves the next free slot under the lock, then
waits for it outside the lock: concurrent callers queue instead of colliding.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from .messages import ErrorCode
from .service import ServiceError

try:
    import fcntl
except ImportError:  # Windows: no cross-process lock, the in-process lock still applies
    fcntl = None  # type: ignore[assignment]

_LOCAL = asyncio.Lock()


class FileLimiter:
    def __init__(
        self,
        directory: str | Path,
        min_interval: float,
        daily_limit: int,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.directory = Path(directory)
        self.state_file = self.directory / "limiter.json"
        self.lock_file = self.directory / "limiter.lock"
        self.min_interval = max(0.0, float(min_interval))
        self.daily_limit = max(1, int(daily_limit))
        self.clock = clock
        self.sleep = sleep

    async def acquire(self) -> int:
        """Wait for the next allowed slot; return what is left today.

        Raises ServiceError(rate_limited, not retryable) when today's cap is spent.
        """
        async with _LOCAL:
            slot, remaining = await asyncio.to_thread(self._reserve)
        wait = slot - self.clock()
        if wait > 0:
            await self.sleep(wait)
        return remaining

    def _reserve(self) -> tuple[float, int]:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._locked():
            state = self._read()
            now = self.clock()
            today = datetime.fromtimestamp(now, UTC).date().isoformat()
            if state.get("day") != today:
                state = {"day": today, "count": 0, "last": state.get("last", 0.0)}
            if state["count"] >= self.daily_limit:
                raise ServiceError(
                    ErrorCode.RATE_LIMITED,
                    f"daily limit of {self.daily_limit} reached; it resets at 00:00 UTC",
                    retryable=False,
                )
            slot = max(now, float(state.get("last", 0.0)) + self.min_interval)
            state["last"] = slot
            state["count"] += 1
            self._write(state)
            return slot, self.daily_limit - state["count"]

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with open(self.lock_file, "a+") as handle:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _read(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, state: dict) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, self.state_file)
