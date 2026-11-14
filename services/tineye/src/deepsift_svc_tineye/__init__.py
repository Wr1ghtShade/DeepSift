"""DeepSift service: reverse image search with the TinEye API (paid search bundles).

Image URLs are searched by URL (TinEye downloads them); images kept in DeepSift's blob
store (``blob:<sha256>``, e.g. a Telegram picture) are uploaded. Every page where a
matching image appears becomes a ``web_page`` entity (rel ``image_found_on``), with
the date TinEye first crawled it: the earliest one often points to the original owner of
a picture reused by a fake profile.

API: ``https://api.tineye.com/rest/search/`` with the key in the ``x-api-key`` header.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, ClassVar

import httpx
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext
from deepsift_sdk.storage import LocalStorage

__all__ = ["TinEyeService"]

API = "https://api.tineye.com/rest/search/"
CONFIDENCE = 0.7  # the same picture, as judged by TinEye


class TinEyeService(Service):
    #: Tests swap in an httpx.MockTransport.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None

    def __init__(self) -> None:
        self.storage = LocalStorage()

    async def run(self, task: Task, ctx: TaskContext) -> None:
        key = os.environ.get("TINEYE_API_KEY")
        if not key:
            raise ServiceError(ErrorCode.NEEDS_CONFIG, "set TINEYE_API_KEY")
        source = task.input.value
        params = {
            "offset": 0,
            "limit": max(1, int(ctx.option("limit"))),
            "sort": "score",
            "order": "desc",
        }
        async with httpx.AsyncClient(
            transport=self.transport, timeout=60.0, headers={"x-api-key": key}
        ) as client:
            try:
                if source.startswith("blob:"):
                    data = await asyncio.to_thread(self.storage.get, source.removeprefix("blob:"))
                    if data is None:
                        raise ServiceError(ErrorCode.INVALID_INPUT, "unknown blob")
                    response = await client.post(
                        API, data=params, files={"image_upload": ("image.jpg", data)}
                    )
                elif source.startswith(("http://", "https://")):
                    response = await client.get(API, params={**params, "image_url": source})
                else:
                    raise ServiceError(ErrorCode.INVALID_INPUT, "not an image URL or a stored blob")
            except httpx.HTTPError as exc:
                raise ServiceError(
                    ErrorCode.UPSTREAM_ERROR, f"TinEye unreachable: {type(exc).__name__}"
                ) from exc
        body = self._check(response)
        await self._report(ctx, body, int(ctx.option("backlinks_per_match")))

    @staticmethod
    def _check(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = {}
        messages = (
            "; ".join(str(m) for m in body.get("messages") or []) or f"HTTP {response.status_code}"
        )
        code = body.get("code", response.status_code)
        if response.status_code == 200 and code == 200:
            return body
        if response.status_code in (401, 403) or code in (401, 403):
            raise ServiceError(ErrorCode.NEEDS_CONFIG, f"TinEye refused the key: {messages}")
        if response.status_code == 429 or "remaining" in messages.lower():
            raise ServiceError(ErrorCode.RATE_LIMITED, f"TinEye: {messages}", retryable=False)
        if response.status_code >= 500:
            raise ServiceError(ErrorCode.UPSTREAM_ERROR, f"TinEye: {messages}")
        raise ServiceError(ErrorCode.INVALID_INPUT, f"TinEye: {messages}", retryable=False)

    @staticmethod
    async def _report(ctx: TaskContext, body: dict[str, Any], per_match: int) -> None:
        matches = (body.get("results") or {}).get("matches") or []
        earliest: tuple[str, str] | None = None
        seen: set[str] = set()
        for match in matches:
            for backlink in (match.get("backlinks") or [])[: max(1, per_match)]:
                page = backlink.get("backlink") or backlink.get("url")
                if not page or page in seen:
                    continue
                seen.add(page)
                crawled = backlink.get("crawl_date") or None
                if crawled and (earliest is None or crawled < earliest[0]):
                    earliest = (crawled, match.get("domain") or page)
                attributes = {
                    "site": match.get("domain"),
                    "image_url": backlink.get("url") or match.get("image_url"),
                    "crawl_date": crawled,
                    "score": match.get("score"),
                    "width": match.get("width"),
                    "height": match.get("height"),
                    "tags": match.get("tags") or None,
                }
                await ctx.found(
                    Entity(
                        type=EntityType.WEB_PAGE,
                        value=page,
                        attributes={k: v for k, v in attributes.items() if v is not None},
                        confidence=CONFIDENCE,
                    ),
                    rel="image_found_on",
                )
        notes = [f"{len(matches)} matching images"]
        if earliest:
            notes.append(f"first seen {earliest[0]} on {earliest[1]}")
        remaining = (body.get("stats") or {}).get("total_remaining_searches")
        if remaining is not None:
            notes.append(f"{remaining} TinEye searches left")
        await ctx.progress(1, 1, ", ".join(notes))
