"""Gateway mode: the CLI sends the search to a DeepSift gateway and follows it live.

Set ``DEEPSIFT_GATEWAY_URL`` (or ``--gateway``) and ``DEEPSIFT_API_TOKEN`` (or
``DEEPSIFT_API_TOKEN_FILE``). For a gateway on this machine, the token is also read
from ``$DEEPSIFT_DATA_DIR/api-token``, where the gateway writes it on first start.

:class:`RemoteRun` exposes what :class:`deepsift_sdk.local.LocalRun` does (input,
findings, links, avatar groups), so the tables and the JSON export are the same.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from deepsift_sdk import Entity, EntityType, Event, EventKind
from deepsift_sdk.local import AvatarGroup, Finding, FoundLink, Key
from deepsift_sdk.manifest import OptionSpec
from deepsift_sdk.messages import ErrorCode, ErrorInfo

API = "/api/v1"


class GatewayError(RuntimeError):
    pass


def find_token(url: str) -> str | None:
    """``DEEPSIFT_API_TOKEN``, ``DEEPSIFT_API_TOKEN_FILE``, or the local gateway's file."""
    token = os.environ.get("DEEPSIFT_API_TOKEN")
    if token:
        return token.strip()
    path = os.environ.get("DEEPSIFT_API_TOKEN_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    host = urlsplit(url).hostname
    if host in ("127.0.0.1", "localhost", "::1"):
        base = os.environ.get("DEEPSIFT_DATA_DIR") or Path.home() / ".local/share/deepsift"
        local = Path(base) / "api-token"
        if local.is_file():
            return local.read_text(encoding="utf-8").strip()
    return None


def ws_url(base: str, path: str) -> str:
    parts = urlsplit(base)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, parts.path.rstrip("/") + path, "", ""))


class Gateway:
    def __init__(self, url: str, token: str, timeout: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.client = httpx.AsyncClient(
            base_url=self.url + API,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GatewayError(f"cannot reach the gateway at {self.url}: {exc}") from exc
        if response.status_code == 401:
            raise GatewayError("the gateway refused the API token")
        if response.is_error:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text
            raise GatewayError(str(detail) if detail else f"HTTP {response.status_code}")
        return response.json() if response.content else None

    async def services(self) -> list[dict[str, Any]]:
        return await self.call("GET", "/services")

    def stream(self, investigation_id: str) -> Any:
        return websockets.connect(
            ws_url(self.url, f"{API}/investigations/{investigation_id}/stream"),
            additional_headers={"Authorization": f"Bearer {self.token}"},
            max_size=1 << 22,
        )


def manifests_for_options(services: list[dict[str, Any]]) -> dict[str, Any]:
    """Shape the gateway's service list like ``discover()`` for ``parse_options``."""
    shims = {}
    for service in services:
        options = {k: OptionSpec.model_validate(v) for k, v in service["options"].items()}
        manifest = SimpleNamespace(options=options)
        shims[service["name"]] = SimpleNamespace(get_manifest=lambda m=manifest: m)
    return shims


def plan(
    services: list[dict[str, Any]],
    entity_type: EntityType,
    only: list[str] | None,
    enable: list[str] | None,
) -> list[str] | None:
    """Services for the selector. ``None`` lets the gateway choose (its defaults)."""
    names = {s["name"] for s in services}
    unknown = sorted((set(only or []) | set(enable or [])) - names)
    if unknown:
        raise ValueError(f"unknown service(s): {', '.join(unknown)}")
    if only:
        return list(only)
    if not enable:
        return None
    chosen = [
        s["name"]
        for s in services
        if entity_type.value in s["inputs"]
        and s["state"] in ("ready", "busy")
        and (s["enabled"] or s["name"] in enable)
    ]
    return chosen


def _event(message: Mapping[str, Any]) -> Event | None:
    """Turn a stream message into the SDK event the lanes understand."""
    kind = message["type"]
    service = message.get("service") or message.get("task", {}).get("service", "")
    task_id = message.get("task_id") or message.get("task", {}).get("id", "")
    match kind:
        case "task.started":
            return Event(task_id=task_id, service=service, event=EventKind.STARTED)
        case "task.progress":
            return Event(
                task_id=task_id,
                service=service,
                event=EventKind.PROGRESS,
                done=message.get("done"),
                total=message.get("total"),
            )
        case "task.entity" | "entity.merged":
            return Event(task_id=task_id, service=service, event=EventKind.ENTITY)
        case "task.completed":
            return Event(task_id=task_id, service=service, event=EventKind.COMPLETED)
        case "task.failed":
            raw = message["task"].get("error") or {}
            try:
                code = ErrorCode(raw.get("code", "internal"))
            except ValueError:
                code = ErrorCode.INTERNAL
            error = ErrorInfo.of(code, str(raw.get("message", "")))
            return Event(task_id=task_id, service=service, event=EventKind.FAILED, error=error)
    return None


def _run_of(message: Mapping[str, Any]) -> str | None:
    if "run_id" in message:
        return message["run_id"]
    if "task" in message:
        return message["task"].get("run_id")
    if "run" in message:
        return message["run"].get("id")
    return None


class RemoteRun:
    """A finished run on the gateway, read back into the CLI's data model."""

    def __init__(self) -> None:
        self.input: Entity | None = None
        self.avatar_groups: list[AvatarGroup] = []
        self._findings: dict[Key, Finding] = {}
        self._links: list[FoundLink] = []
        self.investigation_id: str | None = None
        self.run_id: str | None = None

    @property
    def findings(self) -> list[Finding]:
        return sorted(self._findings.values(), key=lambda f: (-f.score, f.entity.value))

    @property
    def links(self) -> list[FoundLink]:
        return self._links

    def finding(self, key: Key) -> Finding | None:
        return self._findings.get(key)

    def load(self, graph: Mapping[str, Any]) -> None:
        keys: dict[str, Key] = {}
        for node in graph["nodes"]:
            entity = Entity(
                id=node["id"],
                type=EntityType(node["type"]),
                value=node["value"],
                attributes=node["attributes"],
            )
            keys[node["id"]] = entity.key
            if node["selector"]:
                continue
            sources = {s["service"]: s["confidence"] for s in node["sources"]}
            self._findings[entity.key] = Finding(entity, sources, node["avatar_group"])
        self._links = [
            FoundLink(keys[e["source"]], e["rel"], keys[e["target"]])
            for e in graph["edges"]
            if e["source"] in keys and e["target"] in keys
        ]
        self.avatar_groups = [
            AvatarGroup(g["name"], tuple(keys[p] for p in g["profiles"] if p in keys), ())
            for g in graph["avatar_groups"]
        ]


async def investigate(
    gateway: Gateway,
    selector: str,
    entity_type: EntityType | None,
    services: list[str] | None,
    options: dict[str, dict[str, Any]],
    depth: int,
    on_event: Callable[[Event], None],
) -> RemoteRun:
    """Create an investigation, start the run, follow it live, then read the results."""
    result = RemoteRun()
    investigation = await gateway.call("POST", "/investigations", json={"name": selector[:200]})
    result.investigation_id = investigation["id"]
    body: dict[str, Any] = {
        "selector": selector,
        "auto_pivot": depth > 0,
        "max_depth": depth,
        "options": options or None,
    }
    if entity_type is not None:
        body["type"] = entity_type.value
    if services is not None:
        body["services"] = services

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    async with gateway.stream(investigation["id"]) as socket:

        async def receive() -> None:
            async for raw in socket:
                with contextlib.suppress(ValueError):
                    await queue.put(json.loads(raw))

        receiver = asyncio.create_task(receive())
        try:
            run = await gateway.call(
                "POST", f"/investigations/{investigation['id']}/runs", json=body
            )
            result.run_id = run["id"]
            result.input = Entity(type=EntityType(run["type"]), value=run["selector"])
            finished = run["status"] != "running"
            while not finished:
                get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({get, receiver}, return_when=asyncio.FIRST_COMPLETED)
                if get not in done:
                    get.cancel()
                    raise GatewayError("the gateway closed the live stream")
                message = get.result()
                if message.get("type") == "stream.lagged":
                    raise GatewayError("the live stream fell behind; see the results in the GUI")
                if _run_of(message) != run["id"]:
                    continue
                if message["type"] == "run.completed":
                    finished = True
                    continue
                event = _event(message)
                if event is not None:
                    on_event(event)
        finally:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver

    graph = await gateway.call("GET", f"/investigations/{investigation['id']}/graph")
    result.load(graph)
    return result
