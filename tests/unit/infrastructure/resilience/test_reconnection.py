"""Unit-тесты для стратегий переподключения (reconnection.py).

Покрывает:
    1. NoReconnect — одна попытка, прямой success / failure.
    2. ReconnectN — ограниченное число попыток с exponential backoff,
       итоговый ReconnectionError при исчерпании.
    3. ReconnectForever — бесконечные попытки, backoff растёт до max_delay.
    4. Метрики — инкремент счётчиков success / failure / giveup.
    5. build — фабрика стратегий.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# purgatory / tenacity могут отсутствовать в окружении unit-тестов;
# подменяем модули до импорта resilience-пакета.
_purgatory = MagicMock()
sys.modules["purgatory"] = _purgatory
sys.modules["purgatory.domain"] = MagicMock()
sys.modules["purgatory.domain.messages"] = MagicMock()
sys.modules["purgatory.domain.messages.base"] = MagicMock()
sys.modules["purgatory.domain.messages.events"] = MagicMock()
sys.modules["purgatory.domain.model"] = MagicMock()

_tenacity = MagicMock()
sys.modules["tenacity"] = _tenacity

_prometheus = MagicMock()
sys.modules["prometheus_client"] = _prometheus

from src.backend.infrastructure.resilience.reconnection import (
    NoReconnect,
    ReconnectForever,
    ReconnectN,
    ReconnectionError,
    build,
)


@pytest.fixture(autouse=True)
def _patch_metrics():
    with patch(
        "src.backend.infrastructure.resilience.reconnection.reconnect_attempts_total",
        new=MagicMock(),
    ) as mock_counter:
        yield mock_counter


@pytest.fixture
def mock_sleep():
    with patch("asyncio.sleep", new=AsyncMock()) as m:
        yield m


# ---------------------------------------------------------------------------
# NoReconnect
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_reconnect_success(mock_sleep, _patch_metrics):
    dial = AsyncMock(return_value="connected")
    strategy = NoReconnect()
    result = await strategy.run("test-client", dial)

    assert result == "connected"
    dial.assert_awaited_once()
    mock_sleep.assert_not_awaited()

    _patch_metrics.labels.assert_called_once_with(
        client="test-client", outcome="success"
    )
    _patch_metrics.labels.return_value.inc.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_reconnect_failure(mock_sleep, _patch_metrics):
    dial = AsyncMock(side_effect=ConnectionError("boom"))
    strategy = NoReconnect()

    with pytest.raises(ConnectionError, match="boom"):
        await strategy.run("test-client", dial)

    dial.assert_awaited_once()
    mock_sleep.assert_not_awaited()

    _patch_metrics.labels.assert_called_once_with(
        client="test-client", outcome="failure"
    )
    _patch_metrics.labels.return_value.inc.assert_called_once()


# ---------------------------------------------------------------------------
# ReconnectN
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconnect_n_success_after_failures(mock_sleep, _patch_metrics):
    dial = AsyncMock(
        side_effect=[ConnectionError("e1"), ConnectionError("e2"), "ok"]
    )
    strategy = ReconnectN(attempts=3, initial_delay=1.0, multiplier=2.0)
    result = await strategy.run("test-client", dial)

    assert result == "ok"
    assert dial.await_count == 3
    # sleep вызывается между попытками: 1→2 и 2→3
    assert mock_sleep.await_count == 2
    mock_sleep.assert_any_await(1.0)
    mock_sleep.assert_any_await(2.0)

    # метрики: 2 failure + 1 success
    assert _patch_metrics.labels.call_count == 3
    _patch_metrics.labels.assert_any_call(client="test-client", outcome="failure")
    _patch_metrics.labels.assert_any_call(client="test-client", outcome="success")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconnect_n_exhausted_raises(mock_sleep, _patch_metrics):
    exc = ConnectionError("fail")
    dial = AsyncMock(side_effect=[exc, exc, exc])
    strategy = ReconnectN(attempts=3, initial_delay=0.5, multiplier=2.0)

    with pytest.raises(
        ReconnectionError, match="Failed to connect 'test-client' after 3 attempts"
    ):
        await strategy.run("test-client", dial)

    assert dial.await_count == 3
    assert mock_sleep.await_count == 2
    mock_sleep.assert_any_await(0.5)
    mock_sleep.assert_any_await(1.0)

    # метрики: 3 failure (каждая попытка) + 1 giveup (на последней)
    assert _patch_metrics.labels.call_count == 4
    _patch_metrics.labels.assert_any_call(client="test-client", outcome="failure")
    _patch_metrics.labels.assert_any_call(client="test-client", outcome="giveup")


# ---------------------------------------------------------------------------
# ReconnectForever
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconnect_forever_success_after_failures(mock_sleep, _patch_metrics):
    dial = AsyncMock(
        side_effect=[
            ConnectionError("e1"),
            ConnectionError("e2"),
            ConnectionError("e3"),
            "success",
        ]
    )
    strategy = ReconnectForever(
        initial_delay=1.0, max_delay=5.0, multiplier=2.0
    )
    result = await strategy.run("test-client", dial)

    assert result == "success"
    assert dial.await_count == 4
    # sleep: 1.0, 2.0, min(5.0, 4.0)=4.0
    assert mock_sleep.await_count == 3
    mock_sleep.assert_any_await(1.0)
    mock_sleep.assert_any_await(2.0)
    mock_sleep.assert_any_await(4.0)

    # метрики: 3 failure + 1 success
    assert _patch_metrics.labels.call_count == 4
    _patch_metrics.labels.assert_any_call(client="test-client", outcome="failure")
    _patch_metrics.labels.assert_any_call(client="test-client", outcome="success")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconnect_forever_backoff_capped_at_max_delay(mock_sleep):
    dial = AsyncMock(
        side_effect=[
            ConnectionError("e1"),
            ConnectionError("e2"),
            ConnectionError("e3"),
            ConnectionError("e4"),
            ConnectionError("e5"),
            "success",
        ]
    )
    strategy = ReconnectForever(
        initial_delay=1.0, max_delay=3.0, multiplier=2.0
    )
    result = await strategy.run("test-client", dial)

    assert result == "success"
    assert dial.await_count == 6
    # delay sequence: 1.0, 2.0, min(3.0, 4.0)=3.0, min(3.0, 6.0)=3.0, ...
    assert mock_sleep.await_count == 5
    calls = [c.args[0] for c in mock_sleep.await_args_list]
    assert calls == [1.0, 2.0, 3.0, 3.0, 3.0]


# ---------------------------------------------------------------------------
# build factory
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_forever():
    s = build("forever", initial_delay=2.0, max_delay=30.0)
    assert isinstance(s, ReconnectForever)
    assert s.initial_delay == 2.0
    assert s.max_delay == 30.0


@pytest.mark.unit
def test_build_n_attempts():
    s = build("n_attempts", attempts=5, initial_delay=0.5)
    assert isinstance(s, ReconnectN)
    assert s.attempts == 5
    assert s.initial_delay == 0.5


@pytest.mark.unit
def test_build_none():
    s = build("none")
    assert isinstance(s, NoReconnect)


@pytest.mark.unit
def test_build_unknown_raises():
    with pytest.raises(ValueError, match="Unknown reconnection policy"):
        build("unknown")
