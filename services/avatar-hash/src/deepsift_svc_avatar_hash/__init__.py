"""DeepSift service: hashes of an image, to recognise the same avatar across sites.

For each ``image`` entity it reports one ``image_hash`` (rel ``hash``) whose value is
``phash:<64-bit hex>`` and whose attributes hold the pHash, the dHash, the SHA-256, the
size and a ``trivial`` flag for near-blank pictures (default avatars), which must not be
used to link profiles. Grouping happens in the orchestrator, which sees every hash of a
run (contract section 6).

Downloads are restricted to public addresses: image URLs come from scraped pages, and
fetching them from the stack must not let a crafted URL reach the internal network.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from io import BytesIO
from typing import Any, ClassVar
from urllib.parse import urljoin, urlsplit
from urllib.request import getproxies, proxy_bypass

import httpx
import imagehash
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext
from deepsift_sdk.storage import LocalStorage
from PIL import Image, ImageStat, UnidentifiedImageError

__all__ = ["AvatarHashService"]

MAX_REDIRECTS = 3
#: Standard deviation of the grey levels under which a picture counts as blank.
TRIVIAL_STDDEV = 6.0
USER_AGENT = "DeepSift/0.1 (+https://github.com/Wr1ghtShade/deepsift)"
Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")


def _uses_proxy(scheme: str, host: str) -> bool:
    """True when httpx will send this request through a proxy from the environment."""
    proxies = getproxies()
    return bool(proxies.get(scheme) or proxies.get("all")) and not proxy_bypass(host)


async def ensure_public(url: str) -> None:
    """Refuse URLs that are not http(s) or that point to a non-public address.

    Without a proxy, the host is resolved and every address must be public. httpx
    resolves it again when connecting, so a DNS answer that changes in between
    (rebinding) is not covered: egress rules on the host are the second layer.

    Behind a proxy (HTTP(S)_PROXY), DNS is the proxy's job and is often unavailable
    locally, so only the name is checked (private IP literals, localhost, internal
    suffixes, single-label names) and the proxy is trusted to filter the rest.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        raise ServiceError(ErrorCode.INVALID_INPUT, "only http(s) image URLs are supported")
    refused = ServiceError(ErrorCode.INVALID_INPUT, "refusing to fetch a non-public address")
    if _is_ip(host):
        addresses = [host]
    elif _uses_proxy(parts.scheme, host):
        if host == "localhost" or "." not in host or host.endswith(_INTERNAL_SUFFIXES):
            raise refused
        return
    else:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            addresses = await _resolve(host, port)
        except OSError as exc:
            raise ServiceError(ErrorCode.UPSTREAM_ERROR, f"cannot resolve {host}") from exc
    if not addresses or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise refused


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def download(client: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    """GET an image, checking every redirect hop and capping the size."""
    for _ in range(MAX_REDIRECTS + 1):
        await ensure_public(url)
        async with client.stream("GET", url) as response:
            if response.is_redirect and "location" in response.headers:
                url = urljoin(url, response.headers["location"])
                continue
            if response.status_code == 429:
                raise ServiceError(ErrorCode.RATE_LIMITED, "image host throttled the download")
            if response.status_code >= 400:
                raise ServiceError(
                    ErrorCode.UPSTREAM_ERROR,
                    f"image host answered {response.status_code}",
                    retryable=response.status_code >= 500,
                )
            content_type = response.headers.get("content-type", "")
            if content_type and not content_type.startswith(("image/", "application/octet")):
                raise ServiceError(ErrorCode.INVALID_INPUT, f"not an image ({content_type})")
            declared = int(response.headers.get("content-length") or 0)
            if declared > max_bytes:
                raise ServiceError(ErrorCode.INVALID_INPUT, "image is too large")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ServiceError(ErrorCode.INVALID_INPUT, "image is too large")
            return bytes(data)
    raise ServiceError(ErrorCode.UPSTREAM_ERROR, "too many redirects")


def hash_image(data: bytes) -> dict[str, Any]:
    """Perceptual and exact hashes of an image, plus a blank-picture flag. CPU-bound."""
    try:
        with Image.open(BytesIO(data)) as source:
            source.load()
            image_format = source.format
            if source.mode in ("RGBA", "LA", "P"):
                rgba = source.convert("RGBA")
                image = Image.new("RGB", rgba.size, (255, 255, 255))
                image.paste(rgba, mask=rgba.getchannel("A"))
            else:
                image = source.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ServiceError(ErrorCode.INVALID_INPUT, "not a readable image") from exc
    stddev = ImageStat.Stat(image.convert("L")).stddev[0]
    return {
        "algo": "phash",
        "phash": str(imagehash.phash(image)),
        "dhash": str(imagehash.dhash(image)),
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": image.width,
        "height": image.height,
        "format": image_format,
        "trivial": stddev < TRIVIAL_STDDEV,
    }


class AvatarHashService(Service):
    #: Tests swap in an httpx.MockTransport.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None

    def __init__(self) -> None:
        self.storage = LocalStorage()

    async def run(self, task: Task, ctx: TaskContext) -> None:
        source = task.input.value
        if source.startswith("blob:"):
            data = self.storage.get(source.removeprefix("blob:"))
            if data is None:
                raise ServiceError(ErrorCode.INVALID_INPUT, "unknown blob")
        else:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=httpx.Timeout(15.0),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=False,
            ) as client:
                try:
                    data = await download(client, source, int(ctx.option("max_bytes")))
                except httpx.HTTPError as exc:
                    raise ServiceError(
                        ErrorCode.UPSTREAM_ERROR, f"download failed: {type(exc).__name__}"
                    ) from exc

        attributes = await asyncio.to_thread(hash_image, data)
        if ctx.option("store_images"):
            await asyncio.to_thread(self.storage.put, data)
        await ctx.found(
            Entity(
                type=EntityType.IMAGE_HASH,
                value=f"phash:{attributes['phash']}",
                attributes=attributes,
            ),
            rel="hash",
        )
