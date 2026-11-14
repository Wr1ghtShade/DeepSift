"""Unit tests: HTTP goes through httpx.MockTransport and DNS through a fake resolver."""

from __future__ import annotations

from io import BytesIO

import deepsift_svc_avatar_hash as svc
import httpx
import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute
from deepsift_sdk.correlate import PHASH_THRESHOLD, hamming
from PIL import Image, ImageDraw

PUBLIC = "93.184.216.34"


def picture(kind: str, size: int = 256, fmt: str = "PNG", quality: int = 90) -> bytes:
    image = Image.new("RGB", (256, 256), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    if kind == "owl":
        draw.ellipse((40, 30, 216, 226), fill=(90, 60, 30))
        draw.ellipse((80, 80, 120, 120), fill=(250, 250, 200))
        draw.ellipse((136, 80, 176, 120), fill=(250, 250, 200))
        draw.polygon([(128, 130), (115, 160), (141, 160)], fill=(230, 160, 20))
    elif kind == "stripes":
        for x in range(0, 256, 32):
            draw.rectangle((x, 0, x + 15, 255), fill=(20, 20, 160))
    elif kind == "blank":
        pass
    image = image.resize((size, size))
    out = BytesIO()
    image.save(out, format=fmt, **({"quality": quality} if fmt == "JPEG" else {}))
    return out.getvalue()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSIFT_DATA_DIR", str(tmp_path))
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(svc, "getproxies", lambda: {})

    async def resolve(host, port):
        return {"internal.example": ["10.0.0.5"]}.get(host, [PUBLIC])

    monkeypatch.setattr(svc, "_resolve", resolve)


def serve(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        return routes[str(request.url)]()

    return httpx.MockTransport(handler)


async def hash_url(monkeypatch, url, routes, **options):
    monkeypatch.setattr(svc.AvatarHashService, "transport", serve(routes))
    service = svc.AvatarHashService()
    task = Task(
        service="avatar-hash",
        input=Entity(type=EntityType.IMAGE, value=url),
        options=options,
    )
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(service, task, sink)
    found = [e for e in events if e.event is EventKind.ENTITY]
    return final, found, service


def image_response(data: bytes, content_type="image/png"):
    return lambda: httpx.Response(200, content=data, headers={"content-type": content_type})


async def test_hashes_an_image_and_stores_it(monkeypatch):
    data = picture("owl")
    final, (found,), service = await hash_url(
        monkeypatch,
        "https://img.example/owl.png",
        {"https://img.example/owl.png": image_response(data)},
    )
    assert final.event is EventKind.COMPLETED
    attrs = found.entity.attributes
    assert found.entity.value == f"phash:{attrs['phash']}"
    assert found.link.rel == "hash"
    assert (attrs["width"], attrs["height"], attrs["format"]) == (256, 256, "PNG")
    assert attrs["trivial"] is False
    assert service.storage.get(attrs["sha256"]) == data


def test_same_picture_resized_and_recompressed_stays_close():
    original = svc.hash_image(picture("owl"))
    smaller = svc.hash_image(picture("owl", size=96, fmt="JPEG", quality=60))
    other = svc.hash_image(picture("stripes"))
    assert original["sha256"] != smaller["sha256"]
    assert hamming(original["phash"], smaller["phash"]) <= PHASH_THRESHOLD
    assert hamming(original["phash"], other["phash"]) > PHASH_THRESHOLD


def test_blank_pictures_are_trivial():
    assert svc.hash_image(picture("blank"))["trivial"] is True


def test_transparent_png_is_flattened():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((8, 8, 56, 56), fill=(200, 0, 0, 255))
    out = BytesIO()
    image.save(out, format="PNG")
    assert svc.hash_image(out.getvalue())["trivial"] is False


async def test_refuses_private_addresses(monkeypatch):
    final, found, _ = await hash_url(monkeypatch, "http://internal.example/a.png", {})
    assert final.error.code is ErrorCode.INVALID_INPUT
    assert "non-public" in final.error.message
    for url in ("http://127.0.0.1/a.png", "http://[::1]/a.png", "http://169.254.169.254/x"):
        final, _, _ = await hash_url(monkeypatch, url, {})
        assert final.error.code is ErrorCode.INVALID_INPUT, url


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://avatars.example.com/u/1", True),
        ("http://localhost/a.png", False),
        ("http://intranet/a.png", False),
        ("http://nas.lan/a.png", False),
        ("http://printer.local/a.png", False),
        ("http://10.1.2.3/a.png", False),
        ("http://93.184.216.34/a.png", True),
    ],
)
async def test_behind_a_proxy_only_names_are_checked(monkeypatch, url, allowed):
    monkeypatch.setattr(
        svc, "getproxies", lambda: {"http": "http://proxy:3128", "https": "http://proxy:3128"}
    )

    async def no_dns(host, port):
        raise AssertionError("must not resolve behind a proxy")

    monkeypatch.setattr(svc, "proxy_bypass", lambda host: False)

    monkeypatch.setattr(svc, "_resolve", no_dns)
    if allowed:
        await svc.ensure_public(url)
    else:
        with pytest.raises(svc.ServiceError):
            await svc.ensure_public(url)


async def test_refuses_redirect_to_private_address(monkeypatch):
    routes = {
        "https://img.example/a.png": lambda: httpx.Response(
            302, headers={"location": "http://internal.example/secret"}
        )
    }
    final, found, _ = await hash_url(monkeypatch, "https://img.example/a.png", routes)
    assert final.error.code is ErrorCode.INVALID_INPUT
    assert found == []


async def test_follows_public_redirects(monkeypatch):
    routes = {
        "https://img.example/a.png": lambda: httpx.Response(302, headers={"location": "/b.png"}),
        "https://img.example/b.png": image_response(picture("owl")),
    }
    final, found, _ = await hash_url(monkeypatch, "https://img.example/a.png", routes)
    assert final.event is EventKind.COMPLETED
    assert len(found) == 1


async def test_size_cap(monkeypatch):
    routes = {"https://img.example/big.png": image_response(picture("owl"))}
    final, _, _ = await hash_url(monkeypatch, "https://img.example/big.png", routes, max_bytes=100)
    assert final.error.code is ErrorCode.INVALID_INPUT
    assert "too large" in final.error.message


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            lambda: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
            ErrorCode.INVALID_INPUT,
        ),
        (
            lambda: httpx.Response(200, content=b"garbage", headers={"content-type": "image/png"}),
            ErrorCode.INVALID_INPUT,
        ),
        (lambda: httpx.Response(404), ErrorCode.UPSTREAM_ERROR),
        (lambda: httpx.Response(429), ErrorCode.RATE_LIMITED),
    ],
)
async def test_bad_responses(monkeypatch, response, code):
    final, _, _ = await hash_url(
        monkeypatch, "https://img.example/x.png", {"https://img.example/x.png": response}
    )
    assert final.error.code is code


async def test_reads_stored_blobs(monkeypatch):
    service = svc.AvatarHashService()
    sha = service.storage.put(picture("owl"))
    task = Task(service="avatar-hash", input=Entity(type=EntityType.IMAGE, value=f"blob:{sha}"))
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(service, task, sink)
    assert final.event is EventKind.COMPLETED
