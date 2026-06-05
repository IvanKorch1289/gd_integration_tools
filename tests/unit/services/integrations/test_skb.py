# ruff: noqa: S101
"""Unit tests for APISKBService (services/integrations/skb.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.backend.services.integrations.skb import APISKBService, get_skb_service


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    import src.backend.services.integrations.skb as _mod

    _mod._skb_service_instance = None
    yield
    _mod._skb_service_instance = None


@pytest.fixture()
def stub_settings() -> SimpleNamespace:
    return SimpleNamespace(
        base_url="https://skb.example.com/",
        endpoints={
            "GET_KINDS": "kinds",
            "CREATE_REQUEST": "requests",
            "GET_RESULT": "results/",
            "GET_ORDER_LIST": "orders",
            "CHECK_ADDRESS": "check",
        },
        api_key="skb-key",
        connect_timeout=2,
        read_timeout=5,
        use_waf=False,
    )


@pytest.fixture()
def service(stub_settings: SimpleNamespace) -> APISKBService:
    return APISKBService(skb_settings=stub_settings)


# ── request injects api-key ─────────────────────────────────────

@pytest.mark.asyncio
async def test_request_merges_api_key(service: APISKBService) -> None:
    from src.backend.services.core.base_external_api import BaseExternalAPIClient

    with patch.object(
        BaseExternalAPIClient, "_request", new_callable=AsyncMock
    ) as mock_base:
        await service.get_request_kinds()
        call_kwargs = mock_base.await_args.kwargs
        assert "params" in call_kwargs
        assert call_kwargs["params"]["api-key"] == "skb-key"


# ── get_request_kinds ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_request_kinds_returns_data(service: APISKBService) -> None:
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"kinds": ["a", "b"]}
        result = await service.get_request_kinds()
        assert result == {"kinds": ["a", "b"]}


@pytest.mark.asyncio
async def test_get_request_kinds_uses_waf_in_production(
    stub_settings: SimpleNamespace,
) -> None:
    with patch("src.backend.services.integrations.skb.settings") as mock_settings:
        mock_settings.app.environment = "production"
        mock_settings.http_base_settings.waf_url = "https://waf.bank.ru/skb"
        svc = APISKBService(skb_settings=stub_settings)
        with patch.object(svc, "_request", new_callable=AsyncMock) as mock_req:
            await svc.get_request_kinds()
            call_args = mock_req.await_args
            assert call_args.args[1] == "https://waf.bank.ru/skb"


# ── add_request ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_request_posts_json(service: APISKBService) -> None:
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"id": 1}
        result = await service.add_request({"query": "test"})
        assert result == {"id": 1}
        assert mock_req.await_args.args[0] == "POST"


# ── get_response_by_order ───────────────────────────────────────

@pytest.mark.asyncio
async def test_get_response_by_order_returns_json_by_default(service: APISKBService) -> None:
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"data": {"status": "ok"}}
        result = await service.get_response_by_order(
            UUID("12345678-1234-5678-1234-567812345678")
        )
        assert result == {"data": {"status": "ok"}}
        assert mock_req.await_args.kwargs["response_type"] == "json"


@pytest.mark.asyncio
async def test_get_response_by_order_returns_bytes_for_pdf(service: APISKBService) -> None:
    # код делает response.get("data") даже при response_type="bytes"
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"data": b"pdf-content"}
        result = await service.get_response_by_order(
            UUID("12345678-1234-5678-1234-567812345678"), response_type_str="PDF"
        )
        assert result == b"pdf-content"
        assert mock_req.await_args.kwargs["response_type"] == "bytes"


# ── get_orders_list ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_orders_list_with_pagination(service: APISKBService) -> None:
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"orders": []}
        result = await service.get_orders_list(take=10, skip=5)
        assert result == {"orders": []}
        assert mock_req.await_args.kwargs["params"] == {"take": 10, "skip": 5}


@pytest.mark.asyncio
async def test_get_orders_list_without_pagination(service: APISKBService) -> None:
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        await service.get_orders_list()
        assert mock_req.await_args.kwargs["params"] is None


# ── get_objects_by_address ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_objects_by_address_posts_with_query(service: APISKBService) -> None:
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"objects": []}
        result = await service.get_objects_by_address("Moscow", comment="test")
        assert result == {"objects": []}
        assert mock_req.await_args.kwargs["params"] == {"query": "Moscow", "comment": "test"}


# ── singleton ───────────────────────────────────────────────────

def test_get_skb_service_singleton(stub_settings: SimpleNamespace) -> None:
    with patch("src.backend.services.integrations.skb.settings") as mock_settings:
        mock_settings.skb_api = stub_settings
        s1 = get_skb_service()
        s2 = get_skb_service()
        assert s1 is s2
