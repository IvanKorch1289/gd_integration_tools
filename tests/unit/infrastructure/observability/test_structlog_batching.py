"""Sprint 6 K2 — тесты BatchingStructlogWrapper."""

# ruff: noqa: S101, SLF001

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


def _patch_flag(value: bool):
    """Патчит feature-flag structlog_batching_enabled на is_flag_enabled."""
    return patch(
        "src.backend.core.config.features.feature_flags.structlog_batching_enabled",
        value,
    )


def test_flag_off_emits_directly() -> None:
    """При flag=False каждый log-call идёт в inner мгновенно."""
    from src.backend.infrastructure.observability.structlog_batching import (
        BatchingStructlogWrapper,
    )

    wrapper = BatchingStructlogWrapper()
    inner = MagicMock()
    wrapper.bind_inner(inner)

    with _patch_flag(False):
        wrapper.info("event_1", key="v1")
        wrapper.warning("event_2", key="v2")
        wrapper.error("event_3", key="v3")

    inner.info.assert_called_once_with("event_1", key="v1")
    inner.warning.assert_called_once_with("event_2", key="v2")
    inner.error.assert_called_once_with("event_3", key="v3")
    # Буфер пуст
    assert wrapper.stats()["buffer_size"] == 0


def test_flag_on_buffers_events() -> None:
    """При flag=True события копятся в буфере (без auto-flush)."""
    from src.backend.infrastructure.observability.structlog_batching import (
        BatchingStructlogWrapper,
    )

    # batch_size большой, чтобы sync-trigger flush не сработал
    wrapper = BatchingStructlogWrapper(batch_size=100, flush_interval_ms=10000)
    inner = MagicMock()
    wrapper.bind_inner(inner)

    with _patch_flag(True):
        wrapper.info("event_1", k="v1")
        wrapper.warning("event_2", k="v2")
        wrapper.error("event_3", k="v3")

    # Inner НЕ вызывался (буферизуется)
    inner.info.assert_not_called()
    inner.warning.assert_not_called()
    inner.error.assert_not_called()
    assert wrapper.stats()["buffer_size"] == 3


@pytest.mark.asyncio
async def test_flush_loop_drains_buffer() -> None:
    """Background flush-loop сбрасывает буфер раз в flush_interval_ms."""
    from src.backend.infrastructure.observability.structlog_batching import (
        BatchingStructlogWrapper,
    )

    wrapper = BatchingStructlogWrapper(batch_size=100, flush_interval_ms=50)
    inner = MagicMock()
    wrapper.bind_inner(inner)

    with _patch_flag(True):
        wrapper.info("event_1", k="v1")
        wrapper.warning("event_2", k="v2")
        # Запустить flush-loop
        await wrapper.start()
        # Подождать > flush_interval_ms
        await asyncio.sleep(0.15)
        await wrapper.stop()

    # После flush — inner вызывался
    assert inner.info.call_count >= 1
    assert inner.warning.call_count >= 1
    assert wrapper.stats()["flushed_total"] >= 2
    assert wrapper.stats()["buffer_size"] == 0


def test_max_buffer_size_drops_old_events() -> None:
    """При переполнении max_buffer_size старые события дропаются (deque maxlen)."""
    from src.backend.infrastructure.observability.structlog_batching import (
        BatchingStructlogWrapper,
    )

    wrapper = BatchingStructlogWrapper(
        batch_size=10000, flush_interval_ms=10000, max_buffer_size=10
    )
    inner = MagicMock()
    wrapper.bind_inner(inner)

    with _patch_flag(True):
        for i in range(20):
            wrapper.info(f"event_{i}", index=i)

    # Буфер ограничен 10, дроп счётчик >= 10
    assert wrapper.stats()["buffer_size"] == 10
    assert wrapper.stats()["dropped_count"] >= 10


def test_singleton_get_batching_wrapper() -> None:
    """get_batching_wrapper возвращает один и тот же экземпляр."""
    from src.backend.infrastructure.observability.structlog_batching import (
        get_batching_wrapper,
    )

    w1 = get_batching_wrapper()
    w2 = get_batching_wrapper()
    assert w1 is w2
