# ruff: noqa: S101
"""Wave 1.5: BaseExternalAPIClient → OutboundHttpClient через feature-flag."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class _StubResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.text = "stub"
        self.content = b"stub"

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture()
def stub_settings() -> SimpleNamespace:
    return SimpleNamespace(
        prod_url="https://api.example.com/",
        endpoints={"items": "items"},
        api_key=None,
        connect_timeout=2,
        read_timeout=5,
        use_waf=False,
    )


@pytest.mark.asyncio
async def test_request_uses_facade_when_flag_enabled(
    stub_settings: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase-2: при выставленном флаге _request делегирует OutboundHttpClient."""
    from src.backend.services.core.base_external_api import BaseExternalAPIClient

    facade = MagicMock()
    facade.request = AsyncMock(return_value=_StubResponse({"ok": True}))

    client = BaseExternalAPIClient(settings=stub_settings, outbound_http_client=facade)
    # Подменим self.client.make_request, чтобы убедиться, что мы НЕ туда пошли.
    client.client = MagicMock()
    client.client.make_request = AsyncMock(side_effect=AssertionError("no legacy"))

    result = await client._request("GET", "https://api.example.com/items")
    assert result == {"ok": True}
    facade.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_falls_back_to_legacy_when_flag_off(
    stub_settings: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase-1 (флаг по умолчанию False): прежнее поведение без facade."""
    from src.backend.services.core.base_external_api import BaseExternalAPIClient

    client = BaseExternalAPIClient(settings=stub_settings)
    legacy_call = AsyncMock(return_value={"legacy": True})
    client.client = MagicMock()
    client.client.make_request = legacy_call

    result = await client._request("GET", "https://api.example.com/items")
    assert result == {"legacy": True}
    legacy_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_text_response_from_facade(
    stub_settings: SimpleNamespace,
) -> None:
    from src.backend.services.core.base_external_api import BaseExternalAPIClient

    facade = MagicMock()
    facade.request = AsyncMock(return_value=_StubResponse({"x": 1}))

    client = BaseExternalAPIClient(settings=stub_settings, outbound_http_client=facade)
    result = await client._request(
        "GET", "https://api.example.com/items", response_type="text"
    )
    assert result == "stub"


@pytest.mark.asyncio
async def test_request_facade_propagates_exception(
    stub_settings: SimpleNamespace,
) -> None:
    from src.backend.core.net.waf import WafBypassError, WafDecision
    from src.backend.services.core.base_external_api import BaseExternalAPIClient

    facade = MagicMock()
    facade.request = AsyncMock(
        side_effect=WafBypassError(
            WafDecision(False, "host in deny_hosts", host="bad.example.com")
        )
    )

    client = BaseExternalAPIClient(settings=stub_settings, outbound_http_client=facade)
    with pytest.raises(WafBypassError):
        await client._request("GET", "https://bad.example.com/x")
