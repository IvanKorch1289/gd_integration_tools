# ruff: noqa: S101
"""Тесты подключения AdaptiveTimeoutPolicy к BaseExternalAPIClient (Wave A.3)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.resilience.adaptive_timeout import (
    AdaptiveTimeoutPolicy,
    get_adaptive_timeout_policy,
    reset_adaptive_timeout_policy,
)
from src.backend.services.core.base_external_api import BaseExternalAPIClient


@pytest.fixture(autouse=True)
def _reset_policy() -> Any:
    """Сбрасывает singleton политики после каждого теста."""
    reset_adaptive_timeout_policy()
    yield
    reset_adaptive_timeout_policy()


@pytest.fixture()
def stub_settings() -> SimpleNamespace:
    """Минимальные settings для конструктора BaseExternalAPIClient."""
    return SimpleNamespace(
        prod_url="https://api.example.com/",
        endpoints={"items": "items"},
        api_key=None,
        connect_timeout=2,
        read_timeout=5,
        use_waf=False,
    )


@pytest.fixture()
def http_response_factory() -> Any:
    """Фабрика возвращающая успешный ответ make_request."""
    async def _do_request(**_: Any) -> dict[str, Any]:
        return {"ok": True}

    return _do_request


@pytest.mark.asyncio
async def test_record_latency_after_successful_request(
    stub_settings: SimpleNamespace, http_response_factory: Any
) -> None:
    """После успешного _request policy получает один сэмпл."""
    client = BaseExternalAPIClient(settings=stub_settings)
    client.client = MagicMock()
    client.client.make_request = AsyncMock(side_effect=http_response_factory)

    await client._request("GET", "https://api.example.com/items")

    policy = get_adaptive_timeout_policy()
    assert policy.sample_count("api.example.com", "/items") == 1


@pytest.mark.asyncio
async def test_record_latency_on_exception(
    stub_settings: SimpleNamespace,
) -> None:
    """Даже при исключении HTTP-вызова latency пишется в policy."""
    client = BaseExternalAPIClient(settings=stub_settings)
    client.client = MagicMock()
    client.client.make_request = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await client._request("GET", "https://api.example.com/items")

    policy = get_adaptive_timeout_policy()
    assert policy.sample_count("api.example.com", "/items") == 1


@pytest.mark.asyncio
async def test_timeouts_fallback_until_min_samples(
    stub_settings: SimpleNamespace,
) -> None:
    """Без 10 сэмплов _timeouts() возвращает hardcoded total = connect + read."""
    client = BaseExternalAPIClient(settings=stub_settings)
    timeouts = client._timeouts(host="api.example.com", endpoint="/items")
    # connect=2, read=5 → total=7 (hardcoded default).
    assert timeouts["total_timeout"] == 7.0


@pytest.mark.asyncio
async def test_timeouts_use_policy_after_warmup(
    stub_settings: SimpleNamespace,
) -> None:
    """После 10 сэмплов p99 latency определяет total_timeout."""
    policy = get_adaptive_timeout_policy()
    # 10 одинаковых сэмплов по 4000 мс → p99 = 4.0s × multiplier 1.5 = 6.0s.
    for _ in range(15):
        policy.record_latency("api.example.com", "/items", 4000.0)

    client = BaseExternalAPIClient(settings=stub_settings)
    timeouts = client._timeouts(host="api.example.com", endpoint="/items")
    assert pytest.approx(timeouts["total_timeout"], rel=0.01) == 6.0


@pytest.mark.asyncio
async def test_policy_failure_does_not_break_request(
    stub_settings: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если get_adaptive_timeout_policy() падает — _request всё равно проходит."""
    import src.backend.services.core.base_external_api as module

    def _broken_policy() -> AdaptiveTimeoutPolicy:
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(
        "src.backend.core.resilience.adaptive_timeout.get_adaptive_timeout_policy",
        _broken_policy,
    )

    client = BaseExternalAPIClient(settings=stub_settings)
    client.client = MagicMock()
    client.client.make_request = AsyncMock(return_value={"ok": True})

    # Не должно бросать — exception в policy глотается.
    result = await client._request("GET", "https://api.example.com/items")
    assert result == {"ok": True}
    # Защита от unused-warnings линтером.
    assert module is module
