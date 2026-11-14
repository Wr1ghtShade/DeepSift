"""DeepSift service: the Telegram account behind a phone number or a @username.

Off by default. It works through a dedicated Telegram account, logged in once with
``deepsift-telegram login``, and the official API (TELEGRAM_API_ID / TELEGRAM_API_HASH
from my.telegram.org). Lookups are paced with a file-based limiter shared by every
process on the machine.

Reported, all linked from the Telegram profile:

- ``profile`` (``t.me/<username>``, else ``tg://user?id=<id>``), found_on the input;
- ``image`` (rel avatar): the picture, saved in the blob store as ``blob:<sha256>`` so
  avatar-hash can compare it with other sites;
- ``identity`` (rel identity): the display name;
- ``username`` (rel username) when the input was a phone: it pivots to Sherlock and
  Maigret; ``phone`` (rel phone) when the input was a username and the number is shown.
"""

from __future__ import annotations

import asyncio
from typing import Any

import phonenumbers
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext
from deepsift_sdk.ratelimit import FileLimiter
from deepsift_sdk.storage import LocalStorage

from .gateway import TelethonGateway, TgUser, make_client, session_path

__all__ = ["TelegramService"]

CONFIDENCE = 0.95  # Telegram itself matched the number or the handle


def to_e164(value: str, default_region: str) -> str:
    region = default_region.upper() or None
    if not value.startswith("+") and region is None:
        raise ServiceError(
            ErrorCode.INVALID_INPUT,
            "number has no country code: write it as +33… or set the default_region option",
        )
    try:
        number = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException as exc:
        raise ServiceError(ErrorCode.INVALID_INPUT, f"not a phone number: {exc}") from exc
    if not phonenumbers.is_valid_number(number):
        raise ServiceError(ErrorCode.INVALID_INPUT, "not a valid phone number")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def profile_entity(user: TgUser) -> Entity:
    url = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
    attributes: dict[str, Any] = {
        "site": "Telegram",
        "telegram_id": user.id,
        "username": user.username,
        "other_usernames": [u for u in user.usernames if u != user.username] or None,
        "display_name": user.display_name,
        "bio": user.bio,
        "phone": user.phone,
        "last_seen": user.last_seen,
    }
    for flag in ("bot", "verified", "premium", "scam", "fake"):
        if getattr(user, flag):
            attributes[flag] = True
    return Entity(
        type=EntityType.PROFILE,
        value=url,
        attributes={k: v for k, v in attributes.items() if v is not None},
        confidence=CONFIDENCE,
    )


class TelegramService(Service):
    def __init__(self) -> None:
        self.storage = LocalStorage()
        self._gateway: TelethonGateway | None = None

    def gateway(self) -> TelethonGateway:
        """The Telegram connection, created on first use. Tests replace this method."""
        if self._gateway is None:
            self._gateway = TelethonGateway(make_client())
        return self._gateway

    async def close(self) -> None:
        if self._gateway is not None:
            await self._gateway.close()

    async def run(self, task: Task, ctx: TaskContext) -> None:
        kind = task.input.type
        value = task.input.value
        if kind is EntityType.PHONE:
            value = to_e164(value, str(ctx.option("default_region") or ""))
        elif not value.lstrip("@"):
            raise ServiceError(ErrorCode.INVALID_INPUT, "empty username")

        gateway = self.gateway()
        await gateway.ensure_ready()  # fails before the quota is spent
        limiter = FileLimiter(
            session_path().parent, ctx.option("min_interval"), ctx.option("daily_limit")
        )
        remaining = await limiter.acquire()

        want = {"photo": bool(ctx.option("fetch_photo")), "bio": bool(ctx.option("fetch_bio"))}
        if kind is EntityType.PHONE:
            user = await gateway.by_phone(value, **want)
        else:
            user = await gateway.by_username(value, **want)
        if user is None:
            reason = (
                "no Telegram account found, or its owner does not let others find them by number"
                if kind is EntityType.PHONE
                else "no Telegram user with this username"
            )
            await ctx.progress(1, 1, f"{reason} ({remaining} lookups left today)")
            return
        await self._report(ctx, kind, user)
        await ctx.progress(1, 1, f"{remaining} lookups left today")

    async def _report(self, ctx: TaskContext, kind: EntityType, user: TgUser) -> None:
        profile = profile_entity(user)
        await ctx.found(profile)
        if user.photo:
            sha256 = await asyncio.to_thread(self.storage.put, user.photo)
            await ctx.found(
                Entity(
                    type=EntityType.IMAGE,
                    value=f"blob:{sha256}",
                    attributes={"site": "Telegram", "role": "avatar"},
                    confidence=CONFIDENCE,
                ),
                rel="avatar",
                parent=profile,
            )
        if user.display_name:
            await ctx.found(
                Entity(
                    type=EntityType.IDENTITY,
                    value=user.display_name,
                    attributes={"name": user.display_name, "site": "Telegram"},
                    confidence=0.6,
                ),
                rel="identity",
                parent=profile,
            )
        if kind is EntityType.PHONE and user.username:
            await ctx.found(
                Entity(type=EntityType.USERNAME, value=user.username, confidence=CONFIDENCE),
                rel="username",
                parent=profile,
            )
        if kind is EntityType.USERNAME and user.phone:
            await ctx.found(
                Entity(type=EntityType.PHONE, value=user.phone, confidence=CONFIDENCE),
                rel="phone",
                parent=profile,
            )
