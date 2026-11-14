from __future__ import annotations

import hashlib

import pytest
from deepsift_sdk import EntityType, EventKind
from deepsift_sdk.correlate import cluster, hamming
from deepsift_sdk.local import LocalRun
from deepsift_sdk.storage import LocalStorage
from fakes import AvatarProfileService, FakeHashService, FakeService, make_manifest


def test_hamming():
    assert hamming("ff", "ff") == 0
    assert hamming("ff", "fe") == 1
    assert hamming("0000000000000000", "ffffffffffffffff") == 64


def test_cluster_is_transitive_and_keeps_singletons():
    groups = cluster({"a": "0000", "b": "0007", "c": "003f", "z": "ff00"}, threshold=3)
    as_sets = sorted(sorted(g) for g in groups)
    # a-b are 3 apart, b-c 3 apart: a, b and c chain together; z stays alone.
    assert as_sets == [["a", "b", "c"], ["z"]]


def test_local_storage_deduplicates(tmp_path):
    storage = LocalStorage(tmp_path)
    sha = storage.put(b"picture")
    assert sha == hashlib.sha256(b"picture").hexdigest()
    assert storage.put(b"picture") == sha
    assert storage.get(sha) == b"picture"
    assert (tmp_path / sha[:2] / sha).is_file()
    assert storage.get("0" * 64) is None
    with pytest.raises(ValueError):
        storage.get("../etc/passwd")


async def test_pivots_hash_avatars_and_group_profiles():
    run = LocalRun({"avatar-profiles": AvatarProfileService(), "fake-hash": FakeHashService()})
    events = [event async for event in run.run("alice")]

    hashed = {e.task_id for e in events if e.service == "fake-hash"}
    assert len(hashed) == 3  # one pivot task per avatar

    (group,) = run.avatar_groups
    assert group.name == "A"
    assert [value for _, value in group.profiles] == [
        "https://site-a.example/alice",
        "https://site-b.example/alice",
    ]
    a = run.finding(("profile", "https://site-a.example/alice"))
    c = run.finding(("profile", "https://site-c.example/alice"))
    assert a.avatar_group == "A"
    assert a.score == 0.75  # 0.6 + avatar bonus
    assert c.avatar_group is None
    assert c.score == 0.6


async def test_depth_zero_disables_pivots():
    run = LocalRun(
        {"avatar-profiles": AvatarProfileService(), "fake-hash": FakeHashService()}, max_depth=0
    )
    events = [event async for event in run.run("alice")]
    assert {e.service for e in events} == {"avatar-profiles"}
    assert run.avatar_groups == []


async def test_trivial_images_are_not_grouped():
    class TrivialHashService(FakeHashService):
        async def run(self, task, ctx):
            from deepsift_sdk import Entity

            await ctx.found(
                Entity(
                    type=EntityType.IMAGE_HASH,
                    value="phash:0000000000000000",
                    attributes={"phash": "0000000000000000", "trivial": True},
                ),
                rel="hash",
            )

    run = LocalRun({"avatar-profiles": AvatarProfileService(), "fake-hash": TrivialHashService()})
    [event async for event in run.run("alice")]
    assert run.avatar_groups == []


async def test_only_limits_the_first_hop_not_pivots():
    run = LocalRun({"avatar-profiles": AvatarProfileService(), "fake-hash": FakeHashService()})
    events = [event async for event in run.run("alice", only=["avatar-profiles"])]
    assert "fake-hash" in {e.service for e in events}


async def test_failing_setup_does_not_stall_the_run():
    class BrokenSetup(FakeService):
        _manifest = make_manifest("broken")

        async def setup(self):
            raise OSError("no data")

    run = LocalRun({"broken": BrokenSetup(), "fake": FakeService()})
    events = [event async for event in run.run("alice")]
    failed = [e for e in events if e.event is EventKind.FAILED]
    assert [e.service for e in failed] == ["broken"]
    assert run.findings


def test_max_depth_is_bounded():
    with pytest.raises(ValueError):
        LocalRun({}, max_depth=4)
