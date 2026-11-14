"""Authentication, browser security headers and request hygiene.

Following web.dev / modern-web-guidance "security" (CSP with nonces and Trusted Types,
Fetch Metadata resource isolation, COOP/CORP, ``__Host-`` cookies, Clear-Site-Data):

- **Auth**: a bearer token (CLI, scripts) or a browser session cookie obtained by
  posting that token once. The cookie is ``__Host-``, ``HttpOnly``, ``Secure``,
  ``SameSite=Strict``; only its SHA-256 is stored.
- **CSRF**: cookie-authenticated requests that change state must carry an allowed
  ``Origin``; Fetch Metadata rejects cross-site requests before auth runs.
- **Headers** on every response; a strict CSP (nonce + ``strict-dynamic`` + Trusted
  Types) on the GUI page, ``default-src 'none'`` on everything else.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import UTC, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import SessionRow, now

log = logging.getLogger(__name__)

SESSION_COOKIE = "__Host-deepsift_session"
INSECURE_SESSION_COOKIE = "deepsift_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
REPORTING_ENDPOINTS = 'csp="/api/v1/reports"'


def gui_csp(nonce: str) -> str:
    """CSP for the GUI page: nonce-based scripts, Trusted Types, nothing from elsewhere."""
    return "; ".join(
        (
            f"script-src 'nonce-{nonce}' 'strict-dynamic' 'report-sample'",
            "style-src 'self'",
            "img-src 'self' data: blob:",
            "font-src 'self'",
            "connect-src 'self'",
            "worker-src 'self'",
            "manifest-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "require-trusted-types-for 'script'",
            "trusted-types deepsift",
            "report-to csp",
        )
    )


def new_nonce() -> str:
    return base64.b64encode(secrets.token_bytes(16)).decode("ascii")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def same_token(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


# -- origins ---------------------------------------------------------------------------


def origin_allowed(origin: str | None, host: str | None, allowed: list[str]) -> bool:
    """Same host as the request, or listed in ``DEEPSIFT_ALLOWED_ORIGINS``. Exact match."""
    if not origin or origin == "null":
        return False
    if origin.rstrip("/") in allowed:
        return True
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and bool(host) and parts.netloc == host


# -- sessions --------------------------------------------------------------------------


class Sessions:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], ttl: int) -> None:
        self.sessions = sessions
        self.ttl = ttl

    async def create(self) -> str:
        token = secrets.token_urlsafe(32)
        async with self.sessions.begin() as session:
            await session.execute(delete(SessionRow).where(SessionRow.expires_at < now()))
            session.add(
                SessionRow(
                    token_hash=hash_token(token), expires_at=now() + timedelta(seconds=self.ttl)
                )
            )
        return token

    async def valid(self, token: str | None) -> bool:
        if not token or len(token) > 128:
            return False
        async with self.sessions() as session:
            expires = await session.scalar(
                select(SessionRow.expires_at).where(SessionRow.token_hash == hash_token(token))
            )
        if expires is None:
            return False
        if expires.tzinfo is None:  # SQLite drops the time zone
            expires = expires.replace(tzinfo=UTC)
        return expires > now()

    async def revoke(self, token: str | None) -> None:
        if not token:
            return
        async with self.sessions.begin() as session:
            await session.execute(
                delete(SessionRow).where(SessionRow.token_hash == hash_token(token))
            )


class LoginThrottle:
    """At most ``limit`` failed logins per client in ``window`` seconds."""

    def __init__(self, limit: int = 5, window: float = 600.0) -> None:
        self.limit = limit
        self.window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, client: str) -> deque[float]:
        failures = self._failures[client]
        cutoff = time.monotonic() - self.window
        while failures and failures[0] < cutoff:
            failures.popleft()
        return failures

    def blocked(self, client: str) -> bool:
        return len(self._prune(client)) >= self.limit

    def failed(self, client: str) -> None:
        self._prune(client).append(time.monotonic())

    def succeeded(self, client: str) -> None:
        self._failures.pop(client, None)


class Auth:
    """Checks credentials on HTTP requests and WebSocket handshakes."""

    def __init__(
        self,
        token: str,
        sessions: Sessions,
        allowed_origins: list[str],
        secure_cookies: bool = True,
    ) -> None:
        self.token = token
        self.sessions = sessions
        self.allowed_origins = allowed_origins
        self.secure_cookies = secure_cookies

    @property
    def cookie_name(self) -> str:
        # The __Host- prefix requires Secure; plain-HTTP setups behind a test client
        # fall back to a prefix-less name.
        return SESSION_COOKIE if self.secure_cookies else INSECURE_SESSION_COOKIE

    def _bearer(self, authorization: str | None) -> str | None:
        if authorization and authorization[:7].lower() == "bearer ":
            return authorization[7:].strip()
        return None

    async def check(self, request: Request) -> None:
        bearer = self._bearer(request.headers.get("authorization"))
        if bearer is not None:
            if same_token(bearer, self.token):
                return
            raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": "Bearer"})
        if await self.sessions.valid(request.cookies.get(self.cookie_name)):
            if request.method not in SAFE_METHODS and not origin_allowed(
                request.headers.get("origin"), request.headers.get("host"), self.allowed_origins
            ):
                raise HTTPException(403, "origin not allowed")
            return
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})

    async def check_websocket(self, websocket: WebSocket) -> bool:
        origin = websocket.headers.get("origin")
        if origin is not None and not origin_allowed(
            origin, websocket.headers.get("host"), self.allowed_origins
        ):
            return False
        bearer = self._bearer(websocket.headers.get("authorization"))
        if bearer is not None:
            return same_token(bearer, self.token)
        return await self.sessions.valid(websocket.cookies.get(self.cookie_name))


# -- middleware ------------------------------------------------------------------------


class BodyTooLarge(Exception):
    pass


class SecurityMiddleware:
    """Fetch Metadata isolation, body size cap and security headers, for HTTP and WS."""

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: list[str],
        max_body: int = 1 << 20,
        large_body_paths: tuple[str, ...] = ("/api/v1/blobs",),
        max_large_body: int = 10 << 20,
        hsts: bool = False,
    ) -> None:
        self.app = app
        self.allowed_origins = allowed_origins
        self.max_body = max_body
        self.large_body_paths = large_body_paths
        self.max_large_body = max_large_body
        self.hsts = hsts

    def _isolated(self, scope: Scope, headers: dict[str, str]) -> bool:
        """Fetch Metadata resource isolation policy. True means reject."""
        site = headers.get("sec-fetch-site")
        if site is None or site in ("same-origin", "none"):
            return False
        if origin_allowed(headers.get("origin"), headers.get("host"), self.allowed_origins):
            return False
        is_api = scope["path"].startswith("/api/")
        navigate = (
            headers.get("sec-fetch-mode") == "navigate"
            and scope.get("method") == "GET"
            and headers.get("sec-fetch-dest") not in ("object", "embed", "iframe", "frame")
        )
        return is_api or not navigate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}

        if self._isolated(scope, headers):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self._plain(send, 403, b"cross-site request refused")
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        limit = (
            self.max_large_body
            if scope["path"].startswith(self.large_body_paths)
            else self.max_body
        )
        length = headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            await self._plain(send, 413, b"request body too large")
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge
            return message

        started = False

        async def secured_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = self._headers(scope, list(message.get("headers", [])))
            await send(message)

        try:
            await self.app(scope, limited_receive, secured_send)
        except BodyTooLarge:
            if not started:
                await self._plain(send, 413, b"request body too large")

    def _headers(self, scope: Scope, raw: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
        present = {name.lower() for name, _ in raw}
        add: list[tuple[str, str]] = [
            ("x-content-type-options", "nosniff"),
            ("referrer-policy", "no-referrer"),
            ("cross-origin-opener-policy", "same-origin"),
            ("cross-origin-resource-policy", "same-origin"),
            ("x-frame-options", "DENY"),
            (
                "permissions-policy",
                "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
                "serial=(), bluetooth=(), hid=(), browsing-topics=()",
            ),
            ("vary", "Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site"),
            ("reporting-endpoints", REPORTING_ENDPOINTS),
        ]
        if self.hsts:
            add.append(("strict-transport-security", "max-age=31536000; includeSubDomains"))
        if b"content-security-policy" not in present:
            add.append(("content-security-policy", API_CSP))
        if scope["path"].startswith("/api/") and b"cache-control" not in present:
            add.append(("cache-control", "no-store"))
        out = [(k, v) for k, v in raw if k.lower() != b"vary"]
        vary = [v.decode("latin-1") for k, v in raw if k.lower() == b"vary"]
        for name, value in add:
            if name == "vary":
                value = ", ".join([*vary, value])
            elif name.encode() in present:
                continue
            out.append((name.encode("latin-1"), value.encode("latin-1")))
        return out

    async def _plain(self, send: Send, status: int, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"content-security-policy", API_CSP.encode()),
                    (b"vary", b"Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
