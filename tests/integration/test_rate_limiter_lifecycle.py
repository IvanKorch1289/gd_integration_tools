"""Integration-тесты pyrate_limiter shutdown + BoundedInMemoryBucket
(Sprint 1 V16 Single-Entry, Step 3.4)."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio

import pytest
from pyrate_limiter import Duration, Limiter, Rate

from src.backend.core.resilience._pyrate_compat import (
    BoundedInMemoryBucket,
    shutdown_pyrate_leaker,
)


@pytest.mark.asyncio
async def test_shutdown_pyrate_leaker_idempotent_when_no_task() -> None:
    """``shutdown_pyrate_leaker`` без активной leak-task не падает."""
    rate = Rate(10, Duration.SECOND * 1)
    limiter = Limiter(rate)
    # Никаких async-операций ещё не было — leaker.aio_leak_task = None.
    await shutdown_pyrate_leaker(limiter)
    await shutdown_pyrate_leaker(limiter)


@pytest.mark.asyncio
async def test_shutdown_pyrate_leaker_cancels_running_task() -> None:
    """После async try_acquire ``aio_leak_task`` создаётся и отменяется."""
    rate = Rate(10, Duration.SECOND * 1)
    limiter = Limiter(rate)
    # Триггерим создание async-leak-task'а.
    await limiter.try_acquire_async("test-id")
    leaker = getattr(limiter, "_leaker", None) or getattr(
        getattr(limiter, "bucket_factory", None), "_leaker", None
    )
    leak_task = getattr(leaker, "aio_leak_task", None)
    if leak_task is None:
        pytest.skip("pyrate_limiter не запустил async-leak-task в этом окружении")
    assert leak_task is not None
    assert not leak_task.done()

    await shutdown_pyrate_leaker(limiter)

    # Task должна быть отменена / завершена.
    assert leak_task.cancelled() or leak_task.done()


def test_bounded_bucket_inherits_limit_semantics() -> None:
    """BoundedInMemoryBucket уважает rate.limit как обычный InMemoryBucket."""
    from pyrate_limiter.abstracts.rate import RateItem

    rate = Rate(3, Duration.SECOND * 60)
    bucket = BoundedInMemoryBucket([rate], max_items=100)

    for ts in range(3):
        accepted = bucket.put(RateItem("user-1", ts * 1000))
        assert accepted is True

    # 4-й item должен быть отвергнут rate-limit'ом, а не cap'ом.
    over_limit = bucket.put(RateItem("user-1", 4 * 1000))
    assert over_limit is False
    assert bucket.failing_rate is rate


def test_bounded_bucket_caps_items_to_max() -> None:
    """При превышении max_items oldest items вытесняются."""
    from pyrate_limiter.abstracts.rate import RateItem

    # Большой rate.limit, чтобы put'ы не отбрасывались rate-limit'ом.
    rate = Rate(100_000, Duration.SECOND * 3600)
    bucket = BoundedInMemoryBucket([rate], max_items=5)

    # Заполняем до 5 (cap).
    for ts in range(5):
        assert bucket.put(RateItem(f"id-{ts}", ts)) is True
    assert len(bucket.items) == 5

    # 6-й — accepted, но oldest должен быть вытеснен.
    assert bucket.put(RateItem("id-5", 5)) is True
    assert len(bucket.items) == 5
    # Самый старый (id-0) удалён.
    assert all(item.name != "id-0" for item in bucket.items)


def test_bounded_bucket_stats_snapshot() -> None:
    """``stats()`` возвращает наполненность буфера."""
    from pyrate_limiter.abstracts.rate import RateItem

    rate = Rate(100, Duration.SECOND * 60)
    bucket = BoundedInMemoryBucket([rate], max_items=50)

    for ts in range(10):
        bucket.put(RateItem(f"id-{ts}", ts))

    stats = bucket.stats()
    assert stats["items"] == 10
    assert stats["max_items"] == 50
    assert stats["saturation"] == pytest.approx(10 / 50)


@pytest.mark.asyncio
async def test_lifecycle_integration_smoke() -> None:
    """Smoke: создаём Limiter, делаем acquire, корректно останавливаем."""
    rate = Rate(5, Duration.SECOND * 1)
    limiter = Limiter(rate)

    for i in range(3):
        await limiter.try_acquire_async(f"smoke-{i}")

    await shutdown_pyrate_leaker(limiter)

    # Финальный sanity-check: ещё одна остановка не падает.
    await asyncio.sleep(0)
    await shutdown_pyrate_leaker(limiter)
