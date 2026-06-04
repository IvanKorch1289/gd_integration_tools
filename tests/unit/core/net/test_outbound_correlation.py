# ruff: noqa: S101
"""Тесты propagation X-Correlation-ID в :class:`OutboundHttpClient` (S17 K3 W3 D12).

Покрывают:

* inject ``X-Correlation-ID`` из ``correlation_id_var`` ContextVar в outgoing headers;
* caller-override (явный header) сохраняется;
* пустой ContextVar → header не добавляется.

Используем ``httpx.MockTransport`` для unit-тестов без реальной сети.
"""

from __future__ import annotations

import httpx
import pytest

from src.backend.core.net.outbound_http import CORRELATION_ID_HEADER, OutboundHttpClient
from src.backend.infrastructure.observability.correlation import (
    correlation_id_var,
    set_correlation_context,
)


def _make_client_with_capture() -> tuple[OutboundHttpClient, list[httpx.Request]]:
    """Конструировать клиент с MockTransport, собирающим все requests."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = OutboundHttpClient()
    # Подмена nested httpx.AsyncClient на MockTransport-вариант.
    client._client = httpx.AsyncClient(transport=transport)  # type: ignore[attr-defined]
    return client, captured


@pytest.fixture(autouse=True)
def _reset_correlation_var() -> None:
    """Сбросить correlation_id_var перед каждым тестом."""
    correlation_id_var.set("")


@pytest.mark.asyncio
async def test_correlation_id_injected_from_context_var() -> None:
    """С установленным ContextVar → X-Correlation-ID попадает в outgoing headers."""
    set_correlation_context(correlation_id="cid-from-context")
    client, captured = _make_client_with_capture()
    try:
        await client.get("https://example.com/api")
    finally:
        await client.aclose()
    assert len(captured) == 1
    assert captured[0].headers.get(CORRELATION_ID_HEADER) == "cid-from-context"


@pytest.mark.asyncio
async def test_caller_override_wins_over_context() -> None:
    """Явный X-Correlation-ID в headers caller'а имеет приоритет над ContextVar."""
    set_correlation_context(correlation_id="cid-from-context")
    client, captured = _make_client_with_capture()
    try:
        await client.get(
            "https://example.com/api", headers={"X-Correlation-ID": "cid-explicit"}
        )
    finally:
        await client.aclose()
    assert captured[0].headers.get(CORRELATION_ID_HEADER) == "cid-explicit"


@pytest.mark.asyncio
async def test_caller_override_case_insensitive() -> None:
    """Lower-case ``x-correlation-id`` от caller'а не перезаписывается."""
    set_correlation_context(correlation_id="cid-from-context")
    client, captured = _make_client_with_capture()
    try:
        await client.get(
            "https://example.com/api",
            headers={"x-correlation-id": "cid-lower-explicit"},
        )
    finally:
        await client.aclose()
    # Caller-override сохраняется (любой case считается явным).
    value = captured[0].headers.get(CORRELATION_ID_HEADER)
    assert value == "cid-lower-explicit"


@pytest.mark.asyncio
async def test_empty_context_var_omits_header() -> None:
    """Пустой ContextVar → header не добавляется в outgoing request."""
    # correlation_id_var уже пуст после autouse-fixture.
    client, captured = _make_client_with_capture()
    try:
        await client.get("https://example.com/api")
    finally:
        await client.aclose()
    assert CORRELATION_ID_HEADER not in captured[0].headers
