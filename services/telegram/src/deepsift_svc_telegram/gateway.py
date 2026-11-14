"""The only module that talks to Telegram, through Telethon (MIT).

``by_phone`` imports the number as a temporary contact (that is how Telegram's own apps
find people) and deletes it right after; the owner is not notified. Telegram returns the
account only if its owner lets anyone find them by number.
``by_username`` resolves a public @username.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepsift_sdk import ErrorCode, ServiceError
from telethon import TelegramClient, errors, functions, types

_STATUS = {
    types.UserStatusOnline: "online",
    types.UserStatusOffline: "offline (exact time visible)",
    types.UserStatusRecently: "recently",
    types.UserStatusLastWeek: "within a week",
    types.UserStatusLastMonth: "within a month",
    types.UserStatusEmpty: "long ago",
}


@dataclass
class TgUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    usernames: list[str] = field(default_factory=list)
    phone: str | None = None
    bot: bool = False
    verified: bool = False
    premium: bool = False
    scam: bool = False
    fake: bool = False
    last_seen: str | None = None
    bio: str | None = None
    photo: bytes | None = None

    @property
    def display_name(self) -> str | None:
        name = " ".join(part for part in (self.first_name, self.last_name) if part)
        return name or None


def session_path() -> Path:
    base = os.environ.get("DEEPSIFT_DATA_DIR") or Path.home() / ".local" / "share" / "deepsift"
    return Path(base) / "telegram" / "deepsift"


def make_client() -> TelegramClient:
    try:
        api_id = int(os.environ["TELEGRAM_API_ID"])
        api_hash = os.environ["TELEGRAM_API_HASH"]
    except (KeyError, ValueError) as exc:
        raise ServiceError(
            ErrorCode.NEEDS_CONFIG, "set TELEGRAM_API_ID and TELEGRAM_API_HASH (my.telegram.org)"
        ) from exc
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(path), api_id, api_hash)


class TelethonGateway:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def ensure_ready(self) -> None:
        if not self.client.is_connected():
            await self.client.connect()
        if not await self.client.is_user_authorized():
            raise ServiceError(
                ErrorCode.NEEDS_CONFIG,
                'no Telegram account is logged in: run "deepsift-telegram login" '
                "with a dedicated account",
            )

    async def close(self) -> None:
        if self.client.is_connected():
            await self.client.disconnect()

    async def by_phone(self, e164: str, *, photo: bool, bio: bool) -> TgUser | None:
        contact = types.InputPhoneContact(
            client_id=random.getrandbits(62), phone=e164, first_name="DeepSift", last_name=""
        )
        result = await self._call(functions.contacts.ImportContactsRequest([contact]))
        if result.retry_contacts:
            raise ServiceError(
                ErrorCode.RATE_LIMITED,
                "Telegram refused the lookup for now (too many contact imports); retry later",
            )
        if not result.users:
            return None
        user = result.users[0]
        try:
            return await self._describe(user, photo=photo, bio=bio)
        finally:
            await self._call(functions.contacts.DeleteContactsRequest(id=[user]))

    async def by_username(self, username: str, *, photo: bool, bio: bool) -> TgUser | None:
        try:
            resolved = await self._call(
                functions.contacts.ResolveUsernameRequest(username.lstrip("@"))
            )
        except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError):
            return None
        if not isinstance(resolved.peer, types.PeerUser):
            return None  # a channel or a group, not a person
        user = next((u for u in resolved.users if u.id == resolved.peer.user_id), None)
        return await self._describe(user, photo=photo, bio=bio) if user else None

    async def _describe(self, user: types.User, *, photo: bool, bio: bool) -> TgUser:
        names = [u.username for u in (user.usernames or []) if getattr(u, "active", True)]
        info = TgUser(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username or (names[0] if names else None),
            usernames=names,
            phone=f"+{user.phone}" if user.phone else None,
            bot=bool(user.bot),
            verified=bool(user.verified),
            premium=bool(user.premium),
            scam=bool(user.scam),
            fake=bool(user.fake),
            last_seen=_STATUS.get(type(user.status)) if user.status else None,
        )
        if bio:
            full = await self._call(functions.users.GetFullUserRequest(user))
            info.bio = full.full_user.about or None
        if photo and user.photo and not isinstance(user.photo, types.UserProfilePhotoEmpty):
            data = await self.client.download_profile_photo(user, file=bytes)
            info.photo = data or None
        return info

    async def _call(self, request: Any) -> Any:
        try:
            return await self.client(request)
        except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError):
            raise  # "not found" for by_username, not an upstream failure
        except errors.FloodWaitError as exc:
            raise ServiceError(
                ErrorCode.RATE_LIMITED, f"Telegram asks to wait {exc.seconds} s before retrying"
            ) from exc
        except errors.RPCError as exc:
            raise ServiceError(ErrorCode.UPSTREAM_ERROR, f"Telegram error: {exc}") from exc
