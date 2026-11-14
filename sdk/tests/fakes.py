from __future__ import annotations

import asyncio

from deepsift_sdk import Entity, EntityType, Manifest, Service, ServiceError, Task, TaskContext
from deepsift_sdk.messages import ErrorCode


def make_manifest(name: str, **overrides) -> Manifest:
    data = {
        "name": name,
        "version": "0.0.1",
        "inputs": ["username"],
        "outputs": ["profile"],
        "mode": "local",
        "license": "MIT",
        "timeout": "5s",
    }
    data.update(overrides)
    return Manifest.model_validate(data)


class FakeService(Service):
    """Finds the given profiles, or misbehaves on demand through task options."""

    _manifest = make_manifest("fake")
    profiles: tuple[tuple[str, float], ...] = (("https://example.org/u/alice", 0.6),)

    @classmethod
    def get_manifest(cls) -> Manifest:
        return cls._manifest

    async def run(self, task: Task, ctx: TaskContext) -> None:
        behaviour = ctx.option("behaviour")
        if behaviour == "raise":
            raise RuntimeError("boom")
        if behaviour == "service_error":
            raise ServiceError(ErrorCode.RATE_LIMITED, "slow down")
        if behaviour == "sleep":
            await asyncio.sleep(10)
        for done, (url, confidence) in enumerate(self.profiles, start=1):
            await ctx.progress(done, len(self.profiles))
            await ctx.found(Entity(type=EntityType.PROFILE, value=url, confidence=confidence))


class OtherFakeService(FakeService):
    _manifest = make_manifest("other-fake")
    profiles = (("https://example.org/u/alice", 0.7), ("https://other.example/alice", 0.4))
