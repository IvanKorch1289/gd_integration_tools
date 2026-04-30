"""W23.5 — тесты ``entrypoints.webhook.sources_router``.

Минимальное FastAPI-приложение с подключённым только ``sources_router``;
проверяем 200/401/404/400 без поднятия полного app/lifespan.

Чистка ``_cache`` декоратора ``app_state_singleton`` идёт через прямой
доступ к замыканию (приватный API в core/di/app_state.py — стабильный
для тестов).
"""

# ruff: noqa: S101, S105, S106, S108

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI

from src.entrypoints.webhook.sources_router import sources_router
from src.infrastructure.sources.webhook import WebhookSource
from src.services.sources import get_source_registry
from src.services.sources.registry import SourceRegistry


@pytest.fixture
def fresh_registry() -> Iterator[SourceRegistry]:
    """Возвращает свежий ``SourceRegistry`` через заменённый singleton."""
    closure = get_source_registry.__closure__
    cache = next(
        cell.cell_contents
        for cell in closure or ()
        if isinstance(cell.cell_contents, dict)
    )
    cache.pop("source_registry", None)
    registry = get_source_registry()
    yield registry
    cache.pop("source_registry", None)


@pytest.fixture
def app(fresh_registry: SourceRegistry) -> FastAPI:
    """Минимальное FastAPI-приложение только с sources_router."""
    application = FastAPI()
    application.include_router(sources_router)
    return application


@pytest.fixture
async def client(app: FastAPI) -> httpx.AsyncClient:
    """HTTPX AsyncClient через ASGI transport."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as cli:
        yield cli


@pytest.mark.asyncio
async def test_unknown_source_returns_404(
    client: httpx.AsyncClient, fresh_registry: SourceRegistry
) -> None:
    resp = await client.post("/webhooks/sources/missing", json={})
    assert resp.status_code == 404
    assert "missing" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_non_webhook_source_returns_404(
    client: httpx.AsyncClient, fresh_registry: SourceRegistry
) -> None:
    """Source существует, но имеет kind != webhook → 404."""
    from src.infrastructure.sources.file_watcher import FileWatcherSource

    fresh_registry.register(FileWatcherSource("fw1", directory="/tmp", pattern="*.json"))
    resp = await client.post("/webhooks/sources/fw1", json={})
    assert resp.status_code == 404
    assert "kind=file_watcher" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_dispatch_without_secret_returns_200(
    client: httpx.AsyncClient, fresh_registry: SourceRegistry
) -> None:
    captured: list[dict[str, object]] = []

    async def cb(event):  # type: ignore[no-untyped-def]
        captured.append({"id": event.source_id, "payload": event.payload})

    src = WebhookSource("orders_in", path="/orders")
    await src.start(cb)
    fresh_registry.register(src)

    resp = await client.post("/webhooks/sources/orders_in", json={"order_id": 42})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["source_id"] == "orders_in"
    assert captured == [{"id": "orders_in", "payload": {"order_id": 42}}]


@pytest.mark.asyncio
async def test_invalid_hmac_returns_401(
    client: httpx.AsyncClient, fresh_registry: SourceRegistry
) -> None:
    src = WebhookSource("payments", path="/pay", hmac_secret="topsecret")
    await src.start(lambda ev: _noop())
    fresh_registry.register(src)

    resp = await client.post(
        "/webhooks/sources/payments",
        content=b'{"x":1}',
        headers={"X-Signature": "deadbeef", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401
    assert "HMAC" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_valid_hmac_returns_200(
    client: httpx.AsyncClient, fresh_registry: SourceRegistry
) -> None:
    secret = "topsecret"
    body = b'{"x":7}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    captured: list[object] = []

    async def cb(event):  # type: ignore[no-untyped-def]
        captured.append(event.payload)

    src = WebhookSource("events", path="/ev", hmac_secret=secret)
    await src.start(cb)
    fresh_registry.register(src)

    resp = await client.post(
        "/webhooks/sources/events",
        content=body,
        headers={"X-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert captured == [{"x": 7}]


@pytest.mark.asyncio
async def test_invalid_json_returns_400(
    client: httpx.AsyncClient, fresh_registry: SourceRegistry
) -> None:
    src = WebhookSource("raw", path="/raw")
    await src.start(lambda ev: _noop())
    fresh_registry.register(src)

    resp = await client.post(
        "/webhooks/sources/raw",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "Invalid JSON" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_source_not_started_returns_503(
    client: httpx.AsyncClient, fresh_registry: SourceRegistry
) -> None:
    """Source зарегистрирован, но start() не вызывался → RuntimeError → 503."""
    src = WebhookSource("idle", path="/idle")
    fresh_registry.register(src)

    resp = await client.post("/webhooks/sources/idle", json={})
    assert resp.status_code == 503
    assert "не запущен" in resp.json()["detail"]


async def _noop() -> None:
    return None
