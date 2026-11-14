"""The gateway's HTTP and WebSocket API (contract section 7) and the GUI's static files."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import mimetypes
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from deepsift_sdk.entities import SELECTOR_TYPES, EntityType
from deepsift_sdk.local import MAX_DEPTH, discover
from deepsift_sdk.storage import LocalStorage
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from . import export
from .db import (
    EntityRow,
    Investigation,
    LinkRow,
    Run,
    SourceRow,
    TaskRow,
    create_schema,
    iso,
    make_engine,
    make_sessionmaker,
    now,
)
from .executors import BusExecutor, Executor, LocalExecutor
from .hub import Hub
from .orchestrator import Orchestrator, RunError, entity_out, run_out, task_out
from .security import (
    Auth,
    LoginThrottle,
    SecurityMiddleware,
    Sessions,
    gui_csp,
    new_nonce,
    origin_allowed,
    same_token,
)
from .settings import Settings

log = logging.getLogger(__name__)

NONCE_PLACEHOLDER = "__CSP_NONCE__"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
#: Magic numbers of the image formats the gateway accepts and serves.
IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
MAX_ENTITIES = 5000


def sniff_image(data: bytes) -> str | None:
    for signature, mime in IMAGE_SIGNATURES:
        if data.startswith(signature):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


# -- request bodies -------------------------------------------------------------------


class InvestigationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RunIn(BaseModel):
    selector: str = Field(min_length=1, max_length=2048)
    type: EntityType | None = None
    services: list[str] | None = Field(default=None, max_length=64)
    options: dict[str, dict[str, Any]] | None = None
    auto_pivot: bool = False
    max_depth: int = Field(default=1, ge=0, le=MAX_DEPTH)


class PivotIn(BaseModel):
    services: list[str] | None = Field(default=None, max_length=64)
    max_depth: int = Field(default=0, ge=0, le=MAX_DEPTH)


class ServicePatch(BaseModel):
    enabled: bool


class LoginIn(BaseModel):
    token: str = Field(min_length=1, max_length=256)


# -- application ----------------------------------------------------------------------


class Gateway:
    """Everything the routes need, built once per application."""

    def __init__(self, settings: Settings, executor: Executor | None = None) -> None:
        self.settings = settings
        self.engine = make_engine(settings.database_url)
        self.sessions: async_sessionmaker[AsyncSession] = make_sessionmaker(self.engine)
        self.hub = Hub()
        if executor is None:
            if settings.redis_url:
                from deepsift_sdk.bus.redis import RedisBus

                executor = BusExecutor(RedisBus.from_url(settings.redis_url))
            else:
                executor = LocalExecutor({name: cls() for name, cls in discover().items()})
        self.executor = executor
        self.orchestrator = Orchestrator(self.sessions, executor, self.hub)
        self.auth = Auth(
            settings.api_token,
            Sessions(self.sessions, settings.session_ttl),
            settings.allowed_origins,
            settings.secure_cookies,
        )
        self.throttle = LoginThrottle()
        self.storage = LocalStorage(settings.blobs_dir)

    async def start(self) -> None:
        await create_schema(self.engine)
        await self.orchestrator.start()
        if self.settings.token_file is not None:
            log.warning("API token stored in %s (mode 0600)", self.settings.token_file)

    async def stop(self) -> None:
        await self.orchestrator.stop()
        await self.engine.dispose()


def gateway_of(request: Request) -> Gateway:
    return request.app.state.gateway


GatewayDep = Annotated[Gateway, Depends(gateway_of)]


async def authenticated(request: Request) -> None:
    await gateway_of(request).auth.check(request)


async def _investigation(gw: Gateway, investigation_id: str) -> Investigation:
    async with gw.sessions() as session:
        investigation = await session.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(404, "investigation not found")
    return investigation


async def _entities(
    session: AsyncSession,
    investigation_id: str,
    entity_type: EntityType | None = None,
    service: str | None = None,
    min_confidence: float = 0.0,
    limit: int = MAX_ENTITIES,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = select(EntityRow).where(EntityRow.investigation_id == investigation_id)
    if entity_type is not None:
        query = query.where(EntityRow.type == entity_type.value)
    if min_confidence > 0:
        query = query.where(EntityRow.score >= min_confidence)
    if service is not None:
        query = query.where(
            EntityRow.id.in_(select(SourceRow.entity_id).where(SourceRow.service == service))
        )
    query = query.order_by(EntityRow.score.desc(), EntityRow.value).limit(limit).offset(offset)
    rows = (await session.scalars(query)).all()
    sources: dict[str, list[SourceRow]] = {row.id: [] for row in rows}
    if rows:
        found = await session.scalars(
            select(SourceRow).where(SourceRow.entity_id.in_(list(sources)))
        )
        for source in found:
            sources[source.entity_id].append(source)
    return [entity_out(row, sources[row.id]) for row in rows]


def _avatar_groups(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for entity in entities:
        if entity["avatar_group"]:
            groups.setdefault(entity["avatar_group"], []).append(entity["id"])
    return [{"name": name, "profiles": ids} for name, ids in sorted(groups.items())]


def api_router() -> APIRouter:
    public = APIRouter(prefix="/api/v1")
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticated)])

    # -- public: health, session, reports ---------------------------------------------

    @public.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @public.post("/session", status_code=204)
    async def login(body: LoginIn, request: Request, gw: GatewayDep) -> Response:
        client = request.client.host if request.client else "unknown"
        if gw.throttle.blocked(client):
            raise HTTPException(429, "too many failed attempts, try again later")
        if (
            not origin_allowed(
                request.headers.get("origin"),
                request.headers.get("host"),
                gw.settings.allowed_origins,
            )
            and request.headers.get("sec-fetch-site") is not None
        ):
            raise HTTPException(403, "origin not allowed")
        if not same_token(body.token, gw.settings.api_token):
            gw.throttle.failed(client)
            raise HTTPException(401, "invalid token")
        gw.throttle.succeeded(client)
        token = await gw.auth.sessions.create()
        response = Response(status_code=204)
        response.set_cookie(
            gw.auth.cookie_name,
            token,
            max_age=gw.settings.session_ttl,
            path="/",
            secure=gw.settings.secure_cookies,
            httponly=True,
            samesite="strict",
        )
        return response

    @public.get("/session")
    async def whoami(request: Request, gw: GatewayDep) -> dict[str, bool]:
        try:
            await gw.auth.check(request)
        except HTTPException:
            return {"authenticated": False}
        return {"authenticated": True}

    @public.delete("/session", status_code=204)
    async def logout(request: Request, gw: GatewayDep) -> Response:
        await gw.auth.sessions.revoke(request.cookies.get(gw.auth.cookie_name))
        response = Response(status_code=204)
        response.delete_cookie(
            gw.auth.cookie_name,
            path="/",
            secure=gw.settings.secure_cookies,
            httponly=True,
            samesite="strict",
        )
        response.headers["Clear-Site-Data"] = '"cookies", "storage", "cache"'
        return response

    @public.post("/reports", status_code=204)
    async def reports(request: Request) -> Response:
        """CSP violation reports. Only the directive and the blocked origin are logged."""
        try:
            payload = json.loads(await request.body() or b"null")
        except ValueError:
            return Response(status_code=204)
        items = payload if isinstance(payload, list) else [payload]
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            body = item.get("body") or item.get("csp-report") or {}
            if not isinstance(body, dict):
                continue
            directive = str(body.get("effectiveDirective") or body.get("effective-directive"))
            blocked = str(body.get("blockedURL") or body.get("blocked-uri") or "")
            blocked = re.sub(r"[?#].*$", "", blocked)[:200]
            log.warning("CSP violation: %s blocked %s", directive[:60], blocked)
        return Response(status_code=204)

    # -- investigations ---------------------------------------------------------------

    @router.post("/investigations", status_code=201)
    async def create_investigation(body: InvestigationIn, gw: GatewayDep) -> dict[str, Any]:
        async with gw.sessions.begin() as session:
            investigation = Investigation(name=body.name.strip())
            session.add(investigation)
        return {
            "id": investigation.id,
            "name": investigation.name,
            "created_at": iso(investigation.created_at),
        }

    @router.get("/investigations")
    async def list_investigations(gw: GatewayDep) -> list[dict[str, Any]]:
        async with gw.sessions() as session:
            counts = (
                select(EntityRow.investigation_id, func.count().label("n"))
                .group_by(EntityRow.investigation_id)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(Investigation, func.coalesce(counts.c.n, 0))
                    .outerjoin(counts, counts.c.investigation_id == Investigation.id)
                    .order_by(Investigation.created_at.desc())
                )
            ).all()
        return [
            {
                "id": inv.id,
                "name": inv.name,
                "created_at": iso(inv.created_at),
                "entities": count,
            }
            for inv, count in rows
        ]

    @router.get("/investigations/{investigation_id}")
    async def get_investigation(investigation_id: str, gw: GatewayDep) -> dict[str, Any]:
        investigation = await _investigation(gw, investigation_id)
        async with gw.sessions() as session:
            runs = (
                await session.scalars(
                    select(Run)
                    .where(Run.investigation_id == investigation_id)
                    .order_by(Run.created_at.desc())
                )
            ).all()
        return {
            "id": investigation.id,
            "name": investigation.name,
            "created_at": iso(investigation.created_at),
            "runs": [run_out(run) for run in runs],
        }

    @router.delete("/investigations/{investigation_id}", status_code=204)
    async def delete_investigation(investigation_id: str, gw: GatewayDep) -> Response:
        await _investigation(gw, investigation_id)
        async with gw.sessions() as session:
            run_ids = (
                await session.scalars(
                    select(Run.id).where(Run.investigation_id == investigation_id)
                )
            ).all()
        for run_id in run_ids:
            await gw.orchestrator.cancel_run(run_id)
        async with gw.sessions.begin() as session:
            for model in (LinkRow, EntityRow):
                await session.execute(
                    delete(model).where(model.investigation_id == investigation_id)
                )
            await session.execute(delete(TaskRow).where(TaskRow.run_id.in_(run_ids)))
            await session.execute(delete(Run).where(Run.investigation_id == investigation_id))
            await session.execute(delete(Investigation).where(Investigation.id == investigation_id))
        return Response(status_code=204)

    # -- runs -------------------------------------------------------------------------

    @router.post("/investigations/{investigation_id}/runs", status_code=201)
    async def start_run(investigation_id: str, body: RunIn, gw: GatewayDep) -> dict[str, Any]:
        await _investigation(gw, investigation_id)
        if body.type is not None and body.type not in SELECTOR_TYPES:
            raise HTTPException(422, f"{body.type.value} cannot be a selector")
        try:
            run = await gw.orchestrator.start_run(
                investigation_id,
                body.selector,
                body.type,
                body.services,
                body.options,
                body.max_depth if body.auto_pivot else 0,
            )
        except RunError as exc:
            raise HTTPException(422, str(exc)) from exc
        return run_out(run)

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str, gw: GatewayDep) -> dict[str, Any]:
        async with gw.sessions() as session:
            run = await session.get(Run, run_id)
            if run is None:
                raise HTTPException(404, "run not found")
            tasks = (
                await session.scalars(
                    select(TaskRow).where(TaskRow.run_id == run_id).order_by(TaskRow.created_at)
                )
            ).all()
        return {**run_out(run), "tasks": [task_out(task) for task in tasks]}

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, gw: GatewayDep) -> dict[str, Any]:
        async with gw.sessions() as session:
            if await session.get(Run, run_id) is None:
                raise HTTPException(404, "run not found")
        cancelled = await gw.orchestrator.cancel_run(run_id)
        if not cancelled:
            raise HTTPException(409, "run is not running")
        return {"id": run_id, "status": "cancelled"}

    # -- entities ---------------------------------------------------------------------

    @router.get("/investigations/{investigation_id}/entities")
    async def list_entities(
        investigation_id: str,
        gw: GatewayDep,
        type: EntityType | None = None,  # noqa: A002 - public query name
        service: str | None = Query(default=None, max_length=64),
        min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
        limit: int = Query(default=500, ge=1, le=MAX_ENTITIES),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        await _investigation(gw, investigation_id)
        async with gw.sessions() as session:
            return await _entities(
                session, investigation_id, type, service, min_confidence, limit, offset
            )

    @router.get("/investigations/{investigation_id}/graph")
    async def graph(
        investigation_id: str,
        gw: GatewayDep,
        min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    ) -> dict[str, Any]:
        await _investigation(gw, investigation_id)
        async with gw.sessions() as session:
            nodes = await _entities(session, investigation_id, min_confidence=min_confidence)
            links = (
                await session.scalars(
                    select(LinkRow).where(LinkRow.investigation_id == investigation_id)
                )
            ).all()
        ids = {node["id"] for node in nodes}
        edges = [
            {"source": link.source_id, "rel": link.rel, "target": link.target_id}
            for link in links
            if link.source_id in ids and link.target_id in ids
        ]
        return {"nodes": nodes, "edges": edges, "avatar_groups": _avatar_groups(nodes)}

    @router.get("/entities/{entity_id}")
    async def get_entity(entity_id: str, gw: GatewayDep) -> dict[str, Any]:
        async with gw.sessions() as session:
            row = await session.get(EntityRow, entity_id)
            if row is None:
                raise HTTPException(404, "entity not found")
            sources = (
                await session.scalars(select(SourceRow).where(SourceRow.entity_id == entity_id))
            ).all()
            links = (
                await session.scalars(
                    select(LinkRow).where(
                        (LinkRow.source_id == entity_id) | (LinkRow.target_id == entity_id)
                    )
                )
            ).all()
            other_ids = {
                lk.target_id if lk.source_id == entity_id else lk.source_id for lk in links
            }
            others = {
                e.id: e
                for e in (
                    await session.scalars(select(EntityRow).where(EntityRow.id.in_(other_ids)))
                ).all()
            }
        infos, enabled = await gw.orchestrator.services()
        entity_type = EntityType(row.type)
        pivots = [
            {"service": name, "enabled": enabled[name], "state": info.state}
            for name, info in sorted(infos.items())
            if info.manifest.accepts(entity_type)
        ]

        def brief(other_id: str) -> dict[str, Any] | None:
            other = others.get(other_id)
            return {"id": other.id, "type": other.type, "value": other.value} if other else None

        return {
            **entity_out(row, list(sources)),
            "links": [
                {
                    "direction": "out" if lk.source_id == entity_id else "in",
                    "rel": lk.rel,
                    "entity": brief(lk.target_id if lk.source_id == entity_id else lk.source_id),
                }
                for lk in links
            ],
            "pivots": pivots,
        }

    @router.post("/entities/{entity_id}/pivot", status_code=201)
    async def pivot(entity_id: str, body: PivotIn, gw: GatewayDep) -> dict[str, Any]:
        async with gw.sessions() as session:
            row = await session.get(EntityRow, entity_id)
        if row is None:
            raise HTTPException(404, "entity not found")
        try:
            run = await gw.orchestrator.start_run(
                row.investigation_id,
                row.value,
                EntityType(row.type),
                body.services,
                None,
                body.max_depth,
                mark_selector=False,
            )
        except RunError as exc:
            raise HTTPException(422, str(exc)) from exc
        return run_out(run)

    # -- export -----------------------------------------------------------------------

    @router.get("/investigations/{investigation_id}/export")
    async def export_investigation(
        investigation_id: str,
        gw: GatewayDep,
        format: Literal["json", "csv", "html"] = "json",  # noqa: A002 - public query name
    ) -> Response:
        investigation = await _investigation(gw, investigation_id)
        async with gw.sessions() as session:
            entities = await _entities(session, investigation_id)
            links = (
                await session.scalars(
                    select(LinkRow).where(LinkRow.investigation_id == investigation_id)
                )
            ).all()
            runs = (
                await session.scalars(select(Run).where(Run.investigation_id == investigation_id))
            ).all()
        report = {
            "investigation": {"id": investigation.id, "name": investigation.name},
            "exported_at": now().isoformat(),
            "runs": [run_out(run) for run in runs],
            "entities": entities,
            "links": [
                {"source": lk.source_id, "rel": lk.rel, "target": lk.target_id} for lk in links
            ],
            "avatar_groups": _avatar_groups(entities),
        }
        name = investigation.name
        disposition = f'attachment; filename="{export.filename(name, format)}"'
        if format == "csv":
            return PlainTextResponse(
                export.to_csv(entities),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": disposition},
            )
        if format == "html":
            return Response(
                export.to_html(report),
                media_type="text/html; charset=utf-8",
                headers={
                    "Content-Disposition": disposition,
                    "Content-Security-Policy": export.html_csp(),
                },
            )
        return JSONResponse(report, headers={"Content-Disposition": disposition})

    # -- services ---------------------------------------------------------------------

    @router.get("/services")
    async def list_services(gw: GatewayDep) -> list[dict[str, Any]]:
        infos, enabled = await gw.orchestrator.services()
        return [
            {
                "name": name,
                "version": info.manifest.version,
                "description": info.manifest.description,
                "inputs": [t.value for t in info.manifest.inputs],
                "outputs": [t.value for t in info.manifest.outputs],
                "license": info.manifest.license,
                "rate_limit": info.manifest.rate_limit,
                "enabled": enabled[name],
                "enabled_by_default": info.manifest.enabled_by_default,
                "state": info.state,
                "missing": info.missing,
                "options": {key: spec.model_dump() for key, spec in info.manifest.options.items()},
                "instances": [
                    {"id": i.id, "state": i.state, "running": i.running} for i in info.instances
                ],
            }
            for name, info in sorted(infos.items())
        ]

    @router.patch("/services/{name}")
    async def patch_service(name: str, body: ServicePatch, gw: GatewayDep) -> dict[str, Any]:
        infos, _ = await gw.orchestrator.services()
        if name not in infos:
            raise HTTPException(404, "service not found")
        await gw.orchestrator.set_enabled(name, body.enabled)
        return {"name": name, "enabled": body.enabled}

    # -- blobs ------------------------------------------------------------------------

    @router.post("/blobs", status_code=201)
    async def upload_blob(request: Request, gw: GatewayDep) -> dict[str, str]:
        data = await request.body()
        mime = sniff_image(data)
        if mime is None:
            raise HTTPException(415, "only PNG, JPEG, GIF and WebP images are accepted")
        sha256 = await asyncio.to_thread(gw.storage.put, data)
        return {"sha256": sha256, "selector": f"blob:{sha256}", "mime": mime}

    @router.get("/blobs/{sha256}")
    async def get_blob(sha256: str, gw: GatewayDep) -> Response:
        if not SHA256.match(sha256):
            raise HTTPException(404, "blob not found")
        data = await asyncio.to_thread(gw.storage.get, sha256)
        mime = sniff_image(data) if data is not None else None
        if data is None or mime is None:
            raise HTTPException(404, "blob not found")
        return Response(
            data,
            media_type=mime,
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "Content-Disposition": "inline",
            },
        )

    # -- live stream ------------------------------------------------------------------

    @public.websocket("/investigations/{investigation_id}/stream")
    async def stream(websocket: WebSocket, investigation_id: str) -> None:
        gw: Gateway = websocket.app.state.gateway
        if not await gw.auth.check_websocket(websocket):
            await websocket.close(code=1008)
            return
        async with gw.sessions() as session:
            if await session.get(Investigation, investigation_id) is None:
                await websocket.close(code=1008)
                return
        await websocket.accept()
        async with gw.hub.subscribe(investigation_id) as queue:
            receiver = asyncio.create_task(_drain(websocket))
            try:
                while True:
                    getter = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait(
                        {getter, receiver}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if receiver in done:
                        getter.cancel()
                        return
                    message = getter.result()
                    if message is None:
                        await websocket.send_json({"type": "stream.lagged"})
                        await websocket.close(code=1013)
                        return
                    await websocket.send_json(message)
            except WebSocketDisconnect:
                return
            finally:
                receiver.cancel()
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                    await receiver

    return public, router


async def _drain(websocket: WebSocket) -> None:
    """Read (and ignore) client messages until it disconnects."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await websocket.receive_text()


# -- GUI ------------------------------------------------------------------------------


def gui_routes(app: FastAPI, root: Path) -> None:
    """Serve the built GUI: hashed assets as immutable files, everything else as the app
    shell with a fresh CSP nonce (the build marks its own tags with ``__CSP_NONCE__``)."""
    root = root.resolve()
    index = (root / "index.html").read_text(encoding="utf-8")

    @app.get("/{path:path}", include_in_schema=False)
    async def gui(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            if candidate.name == "index.html":
                return _shell(index)
            media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            immutable = path.startswith("assets/")
            return Response(
                await asyncio.to_thread(candidate.read_bytes),
                media_type=media_type,
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable"
                    if immutable
                    else "no-cache",
                },
            )
        return _shell(index)


def _shell(index: str) -> Response:
    nonce = new_nonce()
    return Response(
        index.replace(NONCE_PLACEHOLDER, nonce),
        media_type="text/html; charset=utf-8",
        headers={"Content-Security-Policy": gui_csp(nonce), "Cache-Control": "no-cache"},
    )


def create_app(settings: Settings | None = None, executor: Executor | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    gateway = Gateway(settings, executor)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await gateway.start()
        try:
            yield
        finally:
            await gateway.stop()

    app = FastAPI(
        title="DeepSift gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,  # the Swagger UI loads scripts from a CDN, which the CSP forbids
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.gateway = gateway
    public, router = api_router()
    app.include_router(public)
    app.include_router(router)
    if settings.gui_dir is not None and (settings.gui_dir / "index.html").is_file():
        gui_routes(app, settings.gui_dir)
    app.add_middleware(
        SecurityMiddleware,  # type: ignore[arg-type]
        allowed_origins=settings.allowed_origins,
        hsts=settings.hsts,
    )
    return app
