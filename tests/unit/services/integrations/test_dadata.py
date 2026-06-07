# ruff: noqa: S101
"""Unit tests for APIDADATAService (services/integrations/dadata.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.integrations.dadata import (
    APIDADATAService,
    get_dadata_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    import src.backend.services.integrations.dadata as _mod

    _mod._dadata_service_instance = None
    yield
    _mod._dadata_service_instance = None


@pytest.fixture()
def stub_settings() -> SimpleNamespace:
    return SimpleNamespace(
        base_url="https://dadata.ru/api/",
        endpoints={"GEOLOCATE": "geolocate/address"},
        api_key="secret",
        connect_timeout=2,
        read_timeout=5,
        use_waf=False,
    )


@pytest.fixture()
def service(stub_settings: SimpleNamespace) -> APIDADATAService:
    return APIDADATAService(dadata_settings=stub_settings)


# ── get_geolocate ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_geolocate_builds_payload_and_calls_request(
    service: APIDADATAService, stub_settings: SimpleNamespace
) -> None:
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"suggestions": []}
        result = await service.get_geolocate(lat=55.75, lon=37.62)
        assert result == {"suggestions": []}
        mock_req.assert_awaited_once()
        call_kwargs = mock_req.await_args.kwargs
        assert call_kwargs["json"] == {"lat": 55.75, "lon": 37.62}


@pytest.mark.asyncio
async def test_get_geolocate_includes_optional_params(
    service: APIDADATAService, stub_settings: SimpleNamespace
) -> None:
    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"suggestions": []}
        await service.get_geolocate(
            lat=55.75, lon=37.62, count_results=5, radius_metres=100
        )
        call_kwargs = mock_req.await_args.kwargs
        assert call_kwargs["json"]["count"] == 5
        assert call_kwargs["json"]["radius_meters"] == 100


@pytest.mark.asyncio
async def test_get_geolocate_uses_waf_when_configured(
    stub_settings: SimpleNamespace,
) -> None:
    with patch("src.backend.services.integrations.dadata.settings") as mock_settings:
        mock_settings.http_base_settings.waf_url = "https://waf.bank.ru/"
        svc = APIDADATAService(dadata_settings=stub_settings)
        with patch.object(svc, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"suggestions": []}
            await svc.get_geolocate(lat=0.0, lon=0.0)
            call_args = mock_req.await_args
            assert call_args.args[1] == "https://waf.bank.ru/"
            assert call_args.kwargs["use_waf"] is True


@pytest.mark.asyncio
async def test_get_geolocate_wraps_exception_as_service_error(
    service: APIDADATAService, stub_settings: SimpleNamespace
) -> None:
    from src.backend.core.errors import ServiceError

    with patch.object(service, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = RuntimeError("network down")
        with pytest.raises(ServiceError):
            await service.get_geolocate(lat=0.0, lon=0.0)


# ── singleton ───────────────────────────────────────────────────


def test_get_dadata_service_singleton(stub_settings: SimpleNamespace) -> None:
    with patch("src.backend.services.integrations.dadata.settings") as mock_settings:
        mock_settings.dadata_api = stub_settings
        s1 = get_dadata_service()
        s2 = get_dadata_service()
        assert s1 is s2
