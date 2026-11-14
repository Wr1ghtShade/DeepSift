"""DeepSift service: Gravatar profile of an email address (Gravatar REST API v3).

The email is hashed (SHA-256 of the trimmed, lower-cased address) and looked up:

- ``GET https://api.gravatar.com/v3/profiles/{hash}``: public profile. Works without a
  key with low limits; ``GRAVATAR_API_KEY`` raises them and unlocks more fields.
- ``GET https://gravatar.com/avatar/{hash}?d=404``: whether a picture was uploaded,
  when there is no public profile.

Reported: the Gravatar ``profile`` (found_on the email), its ``image`` (avatar, so
avatar-hash can compare it with other sites), the display name (``identity``) and each
verified account as a ``profile`` (verified_account), with a high confidence since
Gravatar checked them.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, ClassVar

import httpx
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext

__all__ = ["GravatarService", "email_hash"]

API = "https://api.gravatar.com/v3/profiles/"
AVATAR = "https://gravatar.com/avatar/"
USER_AGENT = "DeepSift/0.1 (+https://github.com/Wr1ghtShade/deepsift)"
CONFIDENCE = 0.9  # the email is the account's own address
VERIFIED_CONFIDENCE = 0.85


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


class GravatarService(Service):
    #: Tests swap in an httpx.MockTransport.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None

    async def run(self, task: Task, ctx: TaskContext) -> None:
        email = task.input.value
        if "@" not in email:
            raise ServiceError(ErrorCode.INVALID_INPUT, "not an email address")
        digest = email_hash(email)
        headers = {"User-Agent": USER_AGENT}
        key = os.environ.get("GRAVATAR_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"

        async with httpx.AsyncClient(
            transport=self.transport, timeout=15.0, headers=headers
        ) as client:
            try:
                data = await self._profile(client, digest)
                avatar = (data or {}).get("avatar_url") or await self._avatar(client, digest)
            except httpx.HTTPError as exc:
                raise ServiceError(
                    ErrorCode.UPSTREAM_ERROR, f"gravatar unreachable: {type(exc).__name__}"
                ) from exc

        if data is None and avatar is None:
            return
        await self._report(ctx, email, digest, data or {}, avatar)

    async def _profile(self, client: httpx.AsyncClient, digest: str) -> dict[str, Any] | None:
        response = await client.get(API + digest)
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise ServiceError(ErrorCode.RATE_LIMITED, "gravatar rate limit reached")
        if response.status_code >= 400:
            raise ServiceError(
                ErrorCode.UPSTREAM_ERROR,
                f"gravatar answered {response.status_code}",
                retryable=response.status_code >= 500,
            )
        return response.json()

    async def _avatar(self, client: httpx.AsyncClient, digest: str) -> str | None:
        url = f"{AVATAR}{digest}?d=404&s=256"
        response = await client.head(url)
        return url if response.status_code == 200 else None

    async def _report(
        self,
        ctx: TaskContext,
        email: str,
        digest: str,
        data: dict[str, Any],
        avatar: str | None,
    ) -> None:
        attributes: dict[str, Any] = {"site": "Gravatar", "hash": digest}
        for target, source in (
            ("display_name", "display_name"),
            ("bio", "description"),
            ("location", "location"),
            ("job_title", "job_title"),
            ("company", "company"),
            ("pronouns", "pronouns"),
            ("avatar_url", "avatar_url"),
        ):
            if data.get(source):
                attributes[target] = data[source]
        if avatar:
            attributes.setdefault("avatar_url", avatar)
        profile = Entity(
            type=EntityType.PROFILE,
            value=data.get("profile_url") or f"https://gravatar.com/{digest}",
            attributes=attributes,
            confidence=CONFIDENCE,
        )
        await ctx.found(profile)

        if avatar:
            await ctx.found(
                Entity(
                    type=EntityType.IMAGE,
                    value=avatar,
                    attributes={"site": "Gravatar", "role": "avatar"},
                    confidence=CONFIDENCE,
                ),
                rel="avatar",
                parent=profile,
            )
        name = data.get("display_name")
        if isinstance(name, str) and name.strip() and name.strip() != email:
            await ctx.found(
                Entity(
                    type=EntityType.IDENTITY,
                    value=name.strip(),
                    attributes={"name": name.strip(), "site": "Gravatar"},
                    confidence=0.6,
                ),
                rel="identity",
                parent=profile,
            )
        for account in data.get("verified_accounts") or []:
            url = account.get("url")
            if not url or account.get("is_hidden"):
                continue
            await ctx.found(
                Entity(
                    type=EntityType.PROFILE,
                    value=url,
                    attributes={
                        "site": account.get("service_label") or account.get("service_type"),
                        "verified_by": "Gravatar",
                    },
                    confidence=VERIFIED_CONFIDENCE,
                ),
                rel="verified_account",
                parent=profile,
            )
