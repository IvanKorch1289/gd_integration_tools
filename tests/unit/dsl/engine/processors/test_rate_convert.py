"""Unit-тесты RateConvertProcessor — Wave [wave:s5/k3-w4-processor-pack-4]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.rate_convert import RateConvertProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_rate_convert", True)


@pytest.mark.asyncio
async def test_convert_with_mocked_provider() -> None:
    proc = RateConvertProcessor(
        from_currency="USD",
        to_currency="EUR",
        amount=100,
        to="body.eur",
    )
    ex = _ex({})

    fake_response = MagicMock()
    fake_response.json.return_value = {"rates": {"EUR": 0.92}}
    fake_response.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.get.return_value = fake_response
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "src.backend.core.net.outbound_http.OutboundHttpClient",
        return_value=fake_client,
    ):
        await proc.process(ex, AsyncMock())

    eur = ex.in_message.body["eur"]
    assert eur["amount"] == pytest.approx(92.0, rel=1e-6)
    assert eur["from"] == "USD"
    assert eur["to"] == "EUR"
    assert eur["rate"] == 0.92


@pytest.mark.asyncio
async def test_amount_required() -> None:
    proc = RateConvertProcessor(from_currency="USD", to_currency="EUR")
    ex = _ex({"x": 1})  # body не число и нет amount_source
    await proc.process(ex, AsyncMock())
    assert ex.error is not None and "amount" in ex.error.lower()


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_rate_convert", False)
    proc = RateConvertProcessor(
        from_currency="USD", to_currency="EUR", amount=10
    )
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("rate_convert_status") == "skipped"
