"""Тест интеграции async PayloadScanner в OutboundHttpClient (B-3 finale).

Используем mock для ``httpx.AsyncClient`` — в test-окружении его прямая
инициализация может падать из-за SOCKS proxy env vars.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.net.waf import WafBypassError, WafPolicy


@pytest.mark.asyncio
async def test_outbound_uses_async_scanner_when_provided() -> None:
    """Async-scanner возвращает причину → WafBypassError + httpx не вызывается."""
    calls: list[bytes | None] = []

    async def virus_scanner(payload: bytes | None) -> str | None:
        calls.append(payload)
        return "ClamAV signature: TestVirus"

    policy = WafPolicy(async_payload_scanner=virus_scanner)

    fake_client = MagicMock()
    fake_client.request = AsyncMock()
    fake_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=fake_client):
        from src.backend.core.net.outbound_http import OutboundHttpClient

        client = OutboundHttpClient(policy=policy)
        with pytest.raises(WafBypassError) as excinfo:
            await client.post("https://api.example.com/upload", content=b"infected")
        await client.aclose()

    assert calls == [b"infected"]
    assert "TestVirus" in excinfo.value.decision.reason
    fake_client.request.assert_not_called()


@pytest.mark.asyncio
async def test_outbound_passes_through_when_scanner_clean() -> None:
    """Async-scanner возвращает None → запрос проходит до httpx.request."""

    async def clean_scanner(_payload: bytes | None) -> str | None:
        return None

    policy = WafPolicy(async_payload_scanner=clean_scanner)

    fake_client = MagicMock()
    fake_client.request = AsyncMock(return_value=MagicMock(status_code=200))
    fake_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=fake_client):
        from src.backend.core.net.outbound_http import OutboundHttpClient

        client = OutboundHttpClient(policy=policy)
        await client.post("https://api.example.com/upload", content=b"safe")
        await client.aclose()

    fake_client.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_outbound_uses_sync_path_without_async_scanner() -> None:
    """Если async_payload_scanner is None — берёт sync evaluate path."""

    policy = WafPolicy()  # async_payload_scanner=None
    assert policy.async_payload_scanner is None

    fake_client = MagicMock()
    fake_client.request = AsyncMock(return_value=MagicMock(status_code=200))
    fake_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=fake_client):
        from src.backend.core.net.outbound_http import OutboundHttpClient

        client = OutboundHttpClient(policy=policy)
        await client.get("https://api.example.com/get")
        await client.aclose()

    fake_client.request.assert_awaited_once()
