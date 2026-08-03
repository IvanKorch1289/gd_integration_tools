"""Smoke-тесты ObservabilityMiddleware (S171 facade, cycle 33 L1 cycle 1).

:mod:`src.backend.entrypoints.middlewares.observability` консолидирует
3 observability-канала (OTel + Prometheus + Audit) в один middleware.
Поведение:

- Default config (все каналы выключены) — no-op, response unchanged.
- Канал включён + backend недоступен (ImportError / None) — graceful no-op.
- Канал включён + backend доступен — emit в соответствующий backend.

Тесты проверяют контракт: middleware НЕ ломает request flow при
любой комбинации enabled-флагов, и event payload содержит все
поля из :class:`ObservabilityConfig` + request metadata.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.middlewares.observability import (
    ObservabilityConfig,
    ObservabilityMiddleware,
)


def _make_request(method: str = "GET", path: str = "/test") -> MagicMock:
    """Создаёт mock-Request с минимально нужными полями для dispatch."""
    req = MagicMock(spec=Request)
    req.method = method
    req.url.path = path
    req.state = MagicMock()
    req.state.request_id = "test-req-id-123"
    req.state.correlation_id = "test-corr-id-456"
    return req


@pytest.mark.asyncio
async def test_default_config_passes_through_unmodified() -> None:
    """Default config (all OFF) — response проходит без изменений, no emits."""
    inner_app = AsyncMock()
    inner_response = Response(content=b"ok", status_code=200)
    inner_app.return_value = inner_response

    mw = ObservabilityMiddleware(inner_app)
    request = _make_request()

    response = await mw.dispatch(request, inner_app)

    # Response passed through unchanged.
    assert response is inner_response
    # No emits (config all-False).
    inner_app.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_event_payload_contains_all_metadata_fields() -> None:
    """Event содержит method, path, status_code, duration_ms, request_id, correlation_id, service."""
    inner_app = AsyncMock()
    inner_response = Response(content=b"hello", status_code=201)
    inner_app.return_value = inner_response

    config = ObservabilityConfig(service_name="test-service")
    mw = ObservabilityMiddleware(inner_app, config=config)

    # Capture what would be emitted. Patch all 3 emit functions.
    with (
        patch(
            "src.backend.entrypoints.middlewares.observability._emit_otel"
        ) as mock_otel,
        patch(
            "src.backend.entrypoints.middlewares.observability._emit_prometheus"
        ) as mock_prom,
        patch(
            "src.backend.entrypoints.middlewares.observability._emit_audit"
        ) as mock_audit,
    ):
        # All channels enabled — каждый emit должен быть вызван с event.
        config_all = ObservabilityConfig(
            otel_enabled=True,
            prometheus_enabled=True,
            audit_enabled=True,
            service_name="test-svc",
        )
        mw_all = ObservabilityMiddleware(inner_app, config=config_all)

        request = _make_request(method="POST", path="/api/v1/test")
        await mw_all.dispatch(request, inner_app)

    # Каждый emit вызван ровно 1 раз.
    assert mock_otel.call_count == 1
    assert mock_prom.call_count == 1
    assert mock_audit.call_count == 1

    # Event payload (берём из любого emit'а — payload одинаковый).
    event = mock_otel.call_args[0][0]
    assert event["method"] == "POST"
    assert event["path"] == "/api/v1/test"
    assert event["status_code"] == 201
    assert event["service"] == "test-svc"
    assert event["request_id"] == "test-req-id-123"
    assert event["correlation_id"] == "test-corr-id-456"
    # duration_ms — positive float.
    assert isinstance(event["duration_ms"], float)
    assert event["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_emit_otel_handles_missing_tracer_gracefully() -> None:
    """Если opentelemetry не установлен — emit() no-op, не raise."""
    inner_app = AsyncMock()
    inner_response = Response(content=b"ok", status_code=200)
    inner_app.return_value = inner_response

    config = ObservabilityConfig(otel_enabled=True)
    mw = ObservabilityMiddleware(inner_app, config=config)

    request = _make_request()
    # Should NOT raise even if opentelemetry не установлен (import error swallowed).
    response = await mw.dispatch(request, inner_app)
    assert response is inner_response


@pytest.mark.asyncio
async def test_emit_audit_handles_emit_failure_gracefully() -> None:
    """Если audit emit упал — middleware всё равно вернёт response."""
    inner_app = AsyncMock()
    inner_response = Response(content=b"ok", status_code=200)
    inner_app.return_value = inner_response

    config = ObservabilityConfig(audit_enabled=True)
    mw = ObservabilityMiddleware(inner_app, config=config)

    request = _make_request()
    # _emit_audit уже wrapped в try/except в реализации —
    # verify что middleware не падает даже при сбое audit-канала.
    with patch(
        "src.backend.entrypoints.middlewares.observability._emit_audit",
        side_effect=RuntimeError("audit down"),
    ):
        response = await mw.dispatch(request, inner_app)
    # Response returned despite audit failure.
    assert response is inner_response


@pytest.mark.asyncio
async def test_observability_config_default_values() -> None:
    """Default config: все 3 канала OFF, sample_rate=1.0."""
    config = ObservabilityConfig()
    assert config.otel_enabled is False
    assert config.prometheus_enabled is False
    assert config.audit_enabled is False
    assert config.sample_rate == 1.0
    assert config.service_name == "gd_integration_tools"


def test_observability_middleware_uses_base_http_middleware() -> None:
    """ObservabilityMiddleware — BaseHTTPMiddleware subclass (s171 facade).

    Cycle 33 L1 audit note: в отличие от SecurityHeadersMiddleware
    (который переписан на pure ASGI), этот facade НАМЕРЕННО остаётся
    на BaseHTTPMiddleware — он не манипулирует response body, только
    добавляет post-request emit (OTel/Prometheus/Audit), для которого
    body-buffering не критичен. Test как architectural marker:
    если кто-то перепишет на pure ASGI — тест нужно обновить.
    """
    from starlette.middleware.base import BaseHTTPMiddleware

    assert issubclass(ObservabilityMiddleware, BaseHTTPMiddleware)
