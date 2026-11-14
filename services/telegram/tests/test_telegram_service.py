"""Telegram tests: the gateway runs against a fake Telethon client returning real TL objects;
the service runs against a fake gateway. Nothing leaves the machine."""

from __future__ import annotations

import hashlib

import deepsift_svc_telegram as svc
import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, ServiceError, Task, execute
from deepsift_sdk.local import LocalRun
from deepsift_svc_telegram.gateway import TelethonGateway, TgUser
from telethon import errors, functions, types

USER = types.User(
    id=4242,
    first_name="Night",
    last_name="Owl",
    username="nightowl_77",
    phone="33612345678",
    photo=types.UserProfilePhoto(photo_id=1, dc_id=2),
    status=types.UserStatusRecently(),
    premium=True,
)


class FakeClient:
    def __init__(self, users=(USER,), retry=False, flood=False, authorized=True):
        self.users = list(users)
        self.retry = retry
        self.flood = flood
        self.authorized = authorized
        self.requests = []
        self.connected = False

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def is_user_authorized(self):
        return self.authorized

    async def download_profile_photo(self, user, file=None):
        return b"\x89PNG fake picture"

    async def __call__(self, request):
        self.requests.append(type(request).__name__)
        if self.flood:
            raise errors.FloodWaitError(request=request, capture=30)
        if isinstance(request, functions.contacts.ImportContactsRequest):
            return types.contacts.ImportedContacts(
                imported=[],
                popular_invites=[],
                retry_contacts=[1] if self.retry else [],
                users=self.users,
            )
        if isinstance(request, functions.contacts.DeleteContactsRequest):
            return types.Updates(updates=[], users=[], chats=[], date=None, seq=0)
        if isinstance(request, functions.contacts.ResolveUsernameRequest):
            if request.username != "nightowl_77":
                raise errors.UsernameNotOccupiedError(request=request)
            return types.contacts.ResolvedPeer(
                peer=types.PeerUser(user_id=USER.id), chats=[], users=[USER]
            )
        if isinstance(request, functions.users.GetFullUserRequest):
            full = types.UserFull(
                id=USER.id,
                settings=types.PeerSettings(),
                notify_settings=types.PeerNotifySettings(),
                common_chats_count=0,
                about="I watch at night",
            )
            return types.users.UserFull(full_user=full, chats=[], users=[USER])
        raise AssertionError(f"unexpected request {request!r}")


# --- gateway ---------------------------------------------------------------------------


async def test_gateway_by_phone_describes_and_deletes_the_temporary_contact():
    client = FakeClient()
    user = await TelethonGateway(client).by_phone("+33612345678", photo=True, bio=True)
    assert user.id == 4242
    assert user.username == "nightowl_77"
    assert user.display_name == "Night Owl"
    assert user.phone == "+33612345678"
    assert user.bio == "I watch at night"
    assert user.last_seen == "recently"
    assert user.premium is True
    assert user.photo == b"\x89PNG fake picture"
    assert client.requests == [
        "ImportContactsRequest",
        "GetFullUserRequest",
        "DeleteContactsRequest",
    ]


async def test_gateway_by_phone_not_found_or_refused():
    assert (
        await TelethonGateway(FakeClient(users=[])).by_phone("+1", photo=False, bio=False) is None
    )
    with pytest.raises(ServiceError) as caught:
        await TelethonGateway(FakeClient(retry=True)).by_phone("+1", photo=False, bio=False)
    assert caught.value.info.code is ErrorCode.RATE_LIMITED


async def test_gateway_flood_wait_is_rate_limited():
    with pytest.raises(ServiceError) as caught:
        await TelethonGateway(FakeClient(flood=True)).by_phone("+1", photo=False, bio=False)
    assert caught.value.info.code is ErrorCode.RATE_LIMITED
    assert "30 s" in caught.value.info.message


async def test_gateway_by_username():
    gateway = TelethonGateway(FakeClient())
    user = await gateway.by_username("@nightowl_77", photo=False, bio=False)
    assert user.id == 4242
    assert user.photo is None
    assert await gateway.by_username("nobody_here", photo=False, bio=False) is None


async def test_gateway_requires_a_logged_in_account():
    with pytest.raises(ServiceError) as caught:
        await TelethonGateway(FakeClient(authorized=False)).ensure_ready()
    assert caught.value.info.code is ErrorCode.NEEDS_CONFIG


# --- service ---------------------------------------------------------------------------


class FakeGateway:
    def __init__(self, user=None, ready=True):
        self.user = user
        self.ready = ready
        self.calls = []

    async def ensure_ready(self):
        if not self.ready:
            raise ServiceError(ErrorCode.NEEDS_CONFIG, "not logged in")

    async def by_phone(self, e164, **want):
        self.calls.append(("phone", e164, want))
        return self.user

    async def by_username(self, name, **want):
        self.calls.append(("username", name, want))
        return self.user

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "x")


async def run(gateway, entity_type, value, **options):
    service = svc.TelegramService()
    service.gateway = lambda: gateway
    task = Task(
        service="telegram",
        input=Entity(type=entity_type, value=value),
        options={"min_interval": 0, **options},
    )
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(service, task, sink)
    found = [(e.entity, e.link) for e in events if e.event is EventKind.ENTITY]
    return final, found, events, service


FULL = TgUser(
    id=4242,
    first_name="Night",
    last_name="Owl",
    username="nightowl_77",
    phone="+33612345678",
    bio="I watch at night",
    photo=b"picture bytes",
    premium=True,
)


async def test_phone_lookup_reports_profile_avatar_identity_and_username():
    gateway = FakeGateway(FULL)
    final, found, _, service = await run(gateway, EntityType.PHONE, "+33 6 12 34 56 78")
    assert final.event is EventKind.COMPLETED
    assert gateway.calls == [("phone", "+33612345678", {"photo": True, "bio": True})]
    kinds = [(e.type, link.rel) for e, link in found]
    assert kinds == [
        (EntityType.PROFILE, "found_on"),
        (EntityType.IMAGE, "avatar"),
        (EntityType.IDENTITY, "identity"),
        (EntityType.USERNAME, "username"),
    ]
    profile = found[0][0]
    assert profile.value == "https://t.me/nightowl_77"
    assert profile.attributes["bio"] == "I watch at night"
    assert profile.attributes["premium"] is True
    image = found[1][0]
    sha = hashlib.sha256(b"picture bytes").hexdigest()
    assert image.value == f"blob:{sha}"
    assert service.storage.get(sha) == b"picture bytes"
    assert found[3][0].value == "nightowl_77"


async def test_username_lookup_reports_the_phone_when_shown():
    final, found, _, _ = await run(FakeGateway(FULL), EntityType.USERNAME, "nightowl_77")
    rels = [link.rel for _, link in found]
    assert "phone" in rels and "username" not in rels


async def test_account_without_username_gets_a_tg_link():
    user = TgUser(id=7, first_name="Anon")
    _, found, _, _ = await run(FakeGateway(user), EntityType.PHONE, "+33612345678")
    assert found[0][0].value == "tg://user?id=7"


async def test_not_found_is_a_message():
    final, found, events, _ = await run(FakeGateway(None), EntityType.PHONE, "+33612345678")
    assert final.event is EventKind.COMPLETED
    assert found == []
    assert any("does not let others find them" in (e.message or "") for e in events)


async def test_not_logged_in_fails_before_spending_the_quota(tmp_path):
    final, _, _, _ = await run(FakeGateway(FULL, ready=False), EntityType.PHONE, "+33612345678")
    assert final.error.code is ErrorCode.NEEDS_CONFIG
    assert not (tmp_path / "telegram" / "limiter.json").exists()


async def test_daily_limit(tmp_path):
    gateway = FakeGateway(FULL)
    await run(gateway, EntityType.PHONE, "+33612345678", daily_limit=1)
    final, _, _, _ = await run(gateway, EntityType.PHONE, "+33612345678", daily_limit=1)
    assert final.error.code is ErrorCode.RATE_LIMITED
    assert len(gateway.calls) == 1


async def test_local_numbers_need_a_region():
    final, _, _, _ = await run(FakeGateway(FULL), EntityType.PHONE, "0612345678")
    assert final.error.code is ErrorCode.INVALID_INPUT
    final, _, _, _ = await run(
        FakeGateway(FULL), EntityType.PHONE, "0612345678", default_region="FR"
    )
    assert final.event is EventKind.COMPLETED


def test_opt_in_and_secrets(monkeypatch):
    manifest = svc.TelegramService.get_manifest()
    assert manifest.enabled_by_default is False
    assert manifest.secrets == ["TELEGRAM_API_ID", "TELEGRAM_API_HASH"]
    assert LocalRun({"telegram": svc.TelegramService()}).plan(EntityType.PHONE) == []
    monkeypatch.delenv("TELEGRAM_API_ID")
    enabled = LocalRun({"telegram": svc.TelegramService()}, enabled={"telegram"})
    assert len(enabled.plan(EntityType.PHONE)) == 1  # runs and reports the missing key
