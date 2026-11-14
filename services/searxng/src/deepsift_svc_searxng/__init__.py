"""DeepSift service: web pages that mention a selector, from a SearXNG instance.

SearXNG (https://github.com/searxng/searxng, AGPL-3.0) runs as its own container; this
service only calls its JSON API (``/search?format=json``), so it adds no dependency on
SearXNG's code. The instance is set with ``SEARXNG_URL``; compose.yaml provides one with
the JSON format enabled (deploy/searxng/settings.yml).

The selector is searched between quotes. A domain is searched as a phrase while
excluding the domain itself, to find what others say about it. A phone number is also
searched in its international and national spellings.

Each page becomes a ``web_page`` entity (rel ``mentioned_on``). A page whose title,
snippet or URL contains the selector gets a higher confidence; by default, pages that do
not contain it at all are dropped, as engines often return loose matches.
"""

from __future__ import annotations

import os
import re
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
import phonenumbers
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext

__all__ = ["SearxngService", "queries_for"]

USER_AGENT = "DeepSift/0.1 (+https://github.com/Wr1ghtShade/deepsift)"
MENTIONED = 0.6
LOOSE = 0.3


def queries_for(entity_type: EntityType, value: str, phone_variants: bool) -> list[str]:
    """Search queries for a selector, most precise first."""
    match entity_type:
        case EntityType.DOMAIN:
            return [f'"{value}" -site:{value}']
        case EntityType.PHONE:
            queries = [f'"{value}"']
            if phone_variants and value.startswith("+"):
                try:
                    number = phonenumbers.parse(value)
                except phonenumbers.NumberParseException:
                    return queries
                for fmt in (
                    phonenumbers.PhoneNumberFormat.INTERNATIONAL,
                    phonenumbers.PhoneNumberFormat.NATIONAL,
                ):
                    spelled = f'"{phonenumbers.format_number(number, fmt)}"'
                    if spelled not in queries:
                        queries.append(spelled)
            return queries
        case _:
            return [f'"{value}"']


def _needles(entity_type: EntityType, value: str) -> list[str]:
    """Strings whose presence means a result really mentions the selector."""
    if entity_type is EntityType.PHONE:
        digits = re.sub(r"\D", "", value)
        national = digits[2:] if len(digits) > 9 else digits
        return [digits, national[-9:]]
    return [value.lower()]


def mentions(result: dict[str, Any], entity_type: EntityType, value: str) -> bool:
    text = " ".join(str(result.get(k) or "") for k in ("title", "content", "url"))
    if entity_type is EntityType.PHONE:
        flat = re.sub(r"\D", "", text)
        return any(needle and needle in flat for needle in _needles(entity_type, value))
    return any(needle in text.lower() for needle in _needles(entity_type, value))


class SearxngService(Service):
    #: Tests swap in an httpx.MockTransport.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None

    async def run(self, task: Task, ctx: TaskContext) -> None:
        base = os.environ.get("SEARXNG_URL", "").rstrip("/")
        if not base:
            raise ServiceError(ErrorCode.NEEDS_CONFIG, "set SEARXNG_URL to your SearXNG instance")
        kind, value = task.input.type, task.input.value
        queries = queries_for(kind, value, bool(ctx.option("phone_variants")))
        pages = max(1, int(ctx.option("pages")))
        limit = max(1, int(ctx.option("max_results")))
        keep_loose = bool(ctx.option("include_unmentioned"))

        seen: set[str] = set()
        reported = 0
        unresponsive: set[str] = set()
        total = len(queries) * pages
        done = 0
        async with httpx.AsyncClient(
            transport=self.transport, timeout=30.0, headers={"User-Agent": USER_AGENT}
        ) as client:
            for query in queries:
                for page in range(1, pages + 1):
                    data = await self._search(client, base, query, page)
                    done += 1
                    unresponsive |= {str(e[0]) for e in data.get("unresponsive_engines") or []}
                    for result in data.get("results") or []:
                        url = result.get("url")
                        if not url or url in seen or reported >= limit:
                            continue
                        seen.add(url)
                        mentioned = mentions(result, kind, value)
                        if not mentioned and not keep_loose:
                            continue
                        await ctx.found(self._entity(result, query, mentioned), rel="mentioned_on")
                        reported += 1
                    await ctx.progress(done, total)
        if unresponsive:
            await ctx.progress(
                total, total, f"engines that did not answer: {', '.join(sorted(unresponsive))}"
            )

    async def _search(
        self, client: httpx.AsyncClient, base: str, query: str, page: int
    ) -> dict[str, Any]:
        params = {
            "q": query,
            "format": "json",
            "pageno": page,
            "safesearch": 0,
            "language": "all",
        }
        try:
            response = await client.get(f"{base}/search", params=params)
        except httpx.HTTPError as exc:
            raise ServiceError(
                ErrorCode.UPSTREAM_ERROR,
                f"SearXNG not reachable at {base} ({type(exc).__name__}); "
                "start it with `docker compose up -d searxng` or fix SEARXNG_URL",
            ) from exc
        if response.status_code == 403:
            raise ServiceError(
                ErrorCode.NEEDS_CONFIG,
                "SearXNG refused the JSON format: add json to search.formats in its settings.yml",
            )
        if response.status_code == 429:
            raise ServiceError(ErrorCode.RATE_LIMITED, "SearXNG throttled the search")
        if response.status_code >= 400:
            raise ServiceError(
                ErrorCode.UPSTREAM_ERROR,
                f"SearXNG answered {response.status_code}",
                retryable=response.status_code >= 500,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ServiceError(ErrorCode.UPSTREAM_ERROR, "SearXNG did not answer JSON") from exc

    @staticmethod
    def _entity(result: dict[str, Any], query: str, mentioned: bool) -> Entity:
        url = str(result["url"])
        engines = result.get("engines") or ([result["engine"]] if result.get("engine") else [])
        attributes = {
            "site": urlsplit(url).hostname or url,
            "title": result.get("title") or None,
            "snippet": result.get("content") or None,
            "engines": list(engines) or None,
            "published": result.get("publishedDate") or None,
            "query": query,
            "mentions_selector": mentioned,
        }
        return Entity(
            type=EntityType.WEB_PAGE,
            value=url,
            attributes={k: v for k, v in attributes.items() if v is not None},
            confidence=MENTIONED if mentioned else LOOSE,
        )
