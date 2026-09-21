"""Unit test для Block 2.3 (gap-ai-2.3, ADR-0073).

Проверяет :class:`FallbackTrackingCallback`:

1. Counter ``ai_graph_fallback_total`` инкрементируется при provider-failure.
2. Labels ``model`` и ``reason`` (тип exception) корректно проставлены.
3. Callback не падает при metrics_registry unavailable (graceful).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_failure_callback_increments_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    """FallbackTrackingCallback вызывает counter.labels(...).inc()."""
    from src.backend.services.ai.gateway.callbacks import FallbackTrackingCallback

    fake_counter = MagicMock()
    fake_labeled = MagicMock()
    fake_counter.labels = MagicMock(return_value=fake_labeled)

    cb = FallbackTrackingCallback()
    # Подменяем lazy resolve напрямую — counter уже "инициализирован".
    cb._counter = fake_counter
    cb._initialized = True

    cb(
        {"model": "openai/gpt-4o-mini", "messages": []},
        exception=TimeoutError("connect timeout"),
    )

    fake_counter.labels.assert_called_once_with(
        model="openai/gpt-4o-mini", reason="TimeoutError"
    )
    fake_labeled.inc.assert_called_once_with()


def test_failure_callback_handles_unknown_model() -> None:
    """При отсутствии model в kwargs label='unknown'."""
    from src.backend.services.ai.gateway.callbacks import FallbackTrackingCallback

    fake_counter = MagicMock()
    fake_counter.labels = MagicMock(return_value=MagicMock())

    cb = FallbackTrackingCallback()
    cb._counter = fake_counter
    cb._initialized = True
    cb({}, exception=RuntimeError("boom"))

    fake_counter.labels.assert_called_once_with(model="unknown", reason="RuntimeError")


def test_failure_callback_handles_no_exception() -> None:
    """При exception=None reason='unknown' — graceful."""
    from src.backend.services.ai.gateway.callbacks import FallbackTrackingCallback

    fake_counter = MagicMock()
    fake_counter.labels = MagicMock(return_value=MagicMock())

    cb = FallbackTrackingCallback()
    cb._counter = fake_counter
    cb._initialized = True
    cb({"model": "test"}, exception=None)

    fake_counter.labels.assert_called_once_with(model="test", reason="unknown")


def test_failure_callback_noop_when_counter_unavailable() -> None:
    """При counter=False (registry unavailable) callback не падает."""
    from src.backend.services.ai.gateway.callbacks import FallbackTrackingCallback

    cb = FallbackTrackingCallback()
    cb._counter = False
    cb._initialized = True
    # Не должно бросать исключение.
    cb({"model": "test"}, exception=RuntimeError("x"))


def test_failure_callback_lazy_resolve_counter() -> None:
    """Counter резолвится из metrics_registry при первом вызове."""
    from src.backend.services.ai.gateway.callbacks import FallbackTrackingCallback

    cb = FallbackTrackingCallback()
    # Принудительно re-init.
    cb._initialized = False
    cb._counter = None

    # Должно вызвать metrics_registry.counter; не падать.
    cb({"model": "test"}, exception=RuntimeError("x"))
    assert cb._initialized is True
