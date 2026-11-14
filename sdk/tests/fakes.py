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


class AvatarProfileService(Service):
    """Finds one profile per site, each with an avatar image linked from it."""

    _manifest = make_manifest("avatar-profiles", outputs=["profile", "image"])
    sites: tuple[tuple[str, str], ...] = (
        ("https://site-a.example/alice", "https://img.example/a.png"),
        ("https://site-b.example/alice", "https://img.example/b.png"),
        ("https://site-c.example/alice", "https://img.example/c.png"),
    )

    @classmethod
    def get_manifest(cls) -> Manifest:
        return cls._manifest

    async def run(self, task: Task, ctx: TaskContext) -> None:
        for url, avatar in self.sites:
            profile = Entity(type=EntityType.PROFILE, value=url, confidence=0.6)
            await ctx.found(profile)
            image = Entity(type=EntityType.IMAGE, value=avatar, confidence=0.6)
            await ctx.found(image, rel="avatar", parent=profile)


class FakeHashService(Service):
    """Hashes images from a lookup table, the way avatar-hash does."""

    _manifest = make_manifest("fake-hash", inputs=["image"], outputs=["image_hash"])
    #: a and b are the same picture recompressed (2 bits apart); c is another picture.
    table = {
        "https://img.example/a.png": "ffd8a0c0e0f0f8fc",
        "https://img.example/b.png": "ffd8a0c0e0f0f8ff",
        "https://img.example/c.png": "0123456789abcdef",
    }

    @classmethod
    def get_manifest(cls) -> Manifest:
        return cls._manifest

    async def run(self, task: Task, ctx: TaskContext) -> None:
        phash = self.table[task.input.value]
        await ctx.found(
            Entity(type=EntityType.IMAGE_HASH, value=f"phash:{phash}", attributes={"phash": phash}),
            rel="hash",
        )


class OtherFakeService(FakeService):
    _manifest = make_manifest("other-fake")
    profiles = (("https://example.org/u/alice", 0.7), ("https://other.example/alice", 0.4))
