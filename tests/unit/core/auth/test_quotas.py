"""Sprint 7 K1 — unit-тесты QuotaCheckMiddleware + QuotaPolicy.

Покрывает:
    1. Skip_paths — middleware пропускает /health.
    2. Без tenant header — passthrough (auth-middleware ответственен).
    3. При allowed — app вызывается, ответ передаётся as-is.
    4. При denied — 429 с JSON-телом, app не вызывается.
"""

from __future__ import annotations

import json

import pytest

from src.backend.core.auth.quotas import (
    QuotaCheckMiddleware,
    QuotaPolicy,
    default_tenant_extractor,
)
from src.backend.services.billing.quotas_service import QuotasService, QuotaWindow


@pytest.fixture
def enable_billing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает feature_flag per_tenant_billing_enabled=True."""
    from src.backend.core.config import features as features_mod

    class _FlagsStub:
        per_tenant_billing_enabled = True

    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub())


class _SentinelApp:
    """ASGI-app для тестов — фиксирует, был ли вызов."""

    def __init__(self) -> None:
        self.called = False
        self.last_scope: dict | None = None

    async def __call__(self, scope: dict, receive: object, send) -> None:
        self.called = True
        self.last_scope = scope
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


class _SendCollector:
    """Накапливает все отправленные ASGI-events."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.events.append(message)


async def _noop_receive() -> dict:  # pragma: no cover — не вызывается тестами
    return {"type": "http.request", "body": b""}


def test_default_tenant_extractor_reads_header() -> None:
    """default_tenant_extractor извлекает X-Tenant-Id из ASGI headers."""
    scope = {
        "type": "http",
        "path": "/",
        "headers": [(b"x-tenant-id", b"acme")],
    }
    assert default_tenant_extractor(scope) == "acme"


def test_default_tenant_extractor_returns_none_without_header() -> None:
    """default_tenant_extractor возвращает None если header отсутствует."""
    scope = {"type": "http", "path": "/", "headers": []}
    assert default_tenant_extractor(scope) is None


def test_policy_should_skip_health_path() -> None:
    """QuotaPolicy.should_skip пропускает /health/*."""
    policy = QuotaPolicy(service=QuotasService())
    assert policy.should_skip({"path": "/health"}) is True
    assert policy.should_skip({"path": "/health/live"}) is True
    assert policy.should_skip({"path": "/api/v1/orders"}) is False


@pytest.mark.asyncio
async def test_middleware_skips_health_path() -> None:
    """Middleware пропускает /health без обращения к QuotasService."""
    service = QuotasService(default_window=QuotaWindow(max_rpm=0))
    middleware = QuotaCheckMiddleware(_SentinelApp(), QuotaPolicy(service=service))
    app: _SentinelApp = middleware.app  # type: ignore[assignment]
    send = _SendCollector()
    scope = {"type": "http", "path": "/health", "headers": []}
    await middleware(scope, _noop_receive, send)
    assert app.called is True


@pytest.mark.asyncio
async def test_middleware_passthrough_without_tenant_header() -> None:
    """Без X-Tenant-Id middleware пропускает запрос дальше (auth ответственен)."""
    service = QuotasService(default_window=QuotaWindow(max_rpm=1))
    middleware = QuotaCheckMiddleware(_SentinelApp(), QuotaPolicy(service=service))
    app: _SentinelApp = middleware.app  # type: ignore[assignment]
    send = _SendCollector()
    scope = {"type": "http", "path": "/api/v1/orders", "headers": []}
    await middleware(scope, _noop_receive, send)
    assert app.called is True


@pytest.mark.asyncio
async def test_middleware_allows_within_limit(enable_billing: None) -> None:
    """При allowed=True middleware вызывает app."""
    service = QuotasService(default_window=QuotaWindow(max_rpm=10))
    middleware = QuotaCheckMiddleware(_SentinelApp(), QuotaPolicy(service=service))
    app: _SentinelApp = middleware.app  # type: ignore[assignment]
    send = _SendCollector()
    scope = {
        "type": "http",
        "path": "/api/v1/orders",
        "headers": [(b"x-tenant-id", b"acme")],
    }
    await middleware(scope, _noop_receive, send)
    assert app.called is True


@pytest.mark.asyncio
async def test_middleware_denies_429_when_rpm_exceeded(
    enable_billing: None,
) -> None:
    """При превышении rpm middleware возвращает 429 без вызова app."""
    service = QuotasService(default_window=QuotaWindow(max_rpm=1))
    middleware = QuotaCheckMiddleware(_SentinelApp(), QuotaPolicy(service=service))
    app: _SentinelApp = middleware.app  # type: ignore[assignment]
    scope = {
        "type": "http",
        "path": "/api/v1/orders",
        "headers": [(b"x-tenant-id", b"acme")],
    }
    # Первый запрос проходит, второй превышает.
    send1 = _SendCollector()
    await middleware(scope, _noop_receive, send1)
    assert app.called is True

    # Второй должен получить 429.
    app.called = False
    send2 = _SendCollector()
    await middleware(scope, _noop_receive, send2)
    assert app.called is False
    start = [e for e in send2.events if e.get("type") == "http.response.start"][0]
    assert start["status"] == 429
    body_event = [e for e in send2.events if e.get("type") == "http.response.body"][0]
    payload = json.loads(body_event["body"].decode("utf-8"))
    assert payload["detail"] == "quota_exceeded"
    assert "rpm exceeded" in payload["reason"]
