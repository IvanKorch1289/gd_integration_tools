"""Тесты :class:`OutboundHttpClient` (V15 R-V15-5, S1 DoD).

Используем ``httpx.MockTransport`` для unit-тестов без реальной сети.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.backend.core.net.outbound_http import OutboundHttpClient
from src.backend.core.net.waf import WafBypassError, WafPolicy


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "url": str(request.url)})


@pytest.fixture()
def transport() -> httpx.MockTransport:
    return httpx.MockTransport(_ok_handler)


def _make_client(
    *,
    transport: httpx.MockTransport,
    policy: WafPolicy | None = None,
    capability_check: Any = None,
    audit: Any = None,
) -> OutboundHttpClient:
    """Тестовая фабрика; подменяет transport напрямую."""
    client = OutboundHttpClient(
        policy=policy, capability_check=capability_check, audit=audit
    )
    # Подменяем нижележащий httpx.AsyncClient на MockTransport-вариант.
    client._client._transport = transport  # type: ignore[attr-defined]
    return client


@pytest.mark.asyncio
async def test_request_passes_through_when_waf_allows(
    transport: httpx.MockTransport,
) -> None:
    """Permissive WAF + valid URL → запрос проходит и возвращает 200."""
    client = _make_client(transport=transport)
    response = await client.get("https://example.com/health")
    assert response.status_code == 200
    await client.aclose()


@pytest.mark.asyncio
async def test_request_blocked_by_waf_raises_bypass_error(
    transport: httpx.MockTransport,
) -> None:
    """deny_hosts → :class:`WafBypassError`."""
    policy = WafPolicy(deny_hosts=frozenset({"banned.example.com"}))
    client = _make_client(transport=transport, policy=policy)
    with pytest.raises(WafBypassError) as exc_info:
        await client.get("https://banned.example.com/")
    assert exc_info.value.decision.host == "banned.example.com"
    await client.aclose()


@pytest.mark.asyncio
async def test_request_invokes_capability_check(transport: httpx.MockTransport) -> None:
    """capability_check вызывается с (plugin, 'net.outbound', host)."""
    seen: list[tuple[str, str, str | None]] = []

    def fake_check(plugin: str, capability: str, scope: str | None) -> None:
        seen.append((plugin, capability, scope))

    client = _make_client(transport=transport, capability_check=fake_check)
    await client.get("https://example.com/")
    assert seen == [("core", "net.outbound", "example.com")]
    await client.aclose()


@pytest.mark.asyncio
async def test_capability_denied_propagates(transport: httpx.MockTransport) -> None:
    """capability_check raise → выходит из request наружу."""

    class _Denied(Exception):
        pass

    def deny(*_args: object) -> None:
        raise _Denied("nope")

    client = _make_client(transport=transport, capability_check=deny)
    with pytest.raises(_Denied):
        await client.get("https://example.com/")
    await client.aclose()


@pytest.mark.asyncio
async def test_audit_callback_receives_decision(transport: httpx.MockTransport) -> None:
    """audit вызывается ровно один раз на ``request``."""
    events: list[dict[str, object]] = []

    def audit(event: dict[str, object]) -> None:
        events.append(event)

    client = _make_client(transport=transport, audit=audit)
    await client.get("https://example.com/path")
    assert len(events) == 1
    assert events[0]["event"] == "waf.evaluate"
    assert events[0]["allowed"] is True
    assert events[0]["host"] == "example.com"
    await client.aclose()


@pytest.mark.asyncio
async def test_async_context_manager(transport: httpx.MockTransport) -> None:
    """``async with OutboundHttpClient(...) as c`` корректно закрывается."""
    client = _make_client(transport=transport)
    async with client as c:
        response = await c.get("https://example.com/")
        assert response.status_code == 200
