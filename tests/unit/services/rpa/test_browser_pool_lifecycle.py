"""BrowserPool lifecycle contract test (Priority 3, 2026-10-13).

User spec:
> Обязательные тесты:
> 1. acquire -> success -> release;
> 2. acquire -> exception -> release;
> 3. acquire -> timeout -> release;
> 4. acquire -> task cancellation -> release;
> 5. два tenant/user context не делят cookies/local storage;
> 6. запрещённый URL блокируется WAF/allowlist;
> 7. ошибка сохраняет screenshot/trace и возвращает typed failure;
> 8. shutdown закрывает все contexts и browser.

Реализация:
- используй async context manager и ``try/finally``;
- всегда явно закрывай BrowserContext;
- persistent context только для явно настроенной сессии;
- не создавай новый browser abstraction;
- desktop RPA оставь в Windows worker;
- recorder должен генерировать только draft, требующий проверки.

Этот тест покрывает пункты 1-3 + 8: acquire/release lifecycle.
Real Playwright runtime mock-out через прямой инжект в self._contexts
(тесты не требуют настоящего браузера). Полная live-runtime проверка
делается в integration-тестах или docker-compose.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool, _PooledContext


def _make_pool_with_mock_contexts(size: int = 2) -> PlaywrightBrowserPool:
    """Создать pool с size фейковыми контекстами без запуска playwright.

    Реальный startup() требует браузера; для unit-теста lifecycle мы
    подменяем self._started=True и кладём мок-объекты в self._contexts.
    """
    pool = PlaywrightBrowserPool.__new__(PlaywrightBrowserPool)
    pool._size = size
    pool._prefer_patchright = True
    pool._browser_kind = "chromium"
    pool._headless = True
    pool._viewport = {"width": 1280, "height": 720}
    pool._pw_instance = None
    pool._browser = None
    pool._contexts = [
        _PooledContext(
            context=SimpleNamespace(close=_async_noop), in_use=False, created_at=0.0
        )
        for _ in range(size)
    ]
    pool._semaphore = asyncio.Semaphore(size)
    pool._lock = asyncio.Lock()
    pool._started = True
    return pool


async def _async_noop() -> None:
    return None


# === Priority 3 / 1: acquire -> success -> release ===
@pytest.mark.asyncio
async def test_acquire_success_releases_slot() -> None:
    """Happy path: acquire возвращает context, body executes, release возвращает slot в pool."""
    pool = _make_pool_with_mock_contexts(size=2)

    async with pool.acquire() as ctx_a:
        assert ctx_a is pool._contexts[0].context
        assert pool._contexts[0].in_use is True
        assert pool._contexts[1].in_use is False

    # После выхода из context manager слот снова свободен
    assert pool._contexts[0].in_use is False
    assert pool._contexts[1].in_use is False
    assert pool._semaphore._value == 2  # type: ignore[attr-defined]


# === Priority 3 / 2: acquire -> exception -> release ===
@pytest.mark.asyncio
async def test_acquire_exception_releases_slot() -> None:
    """Исключение в body не приводит к утечке context.

    Это контракт acquire как async context manager: try/finally в реализации
    должен гарантировать, что семафор освобождается и флаг in_use сбрасывается
    даже при исключении.
    """
    pool = _make_pool_with_mock_contexts(size=1)

    with pytest.raises(RuntimeError, match="boom"):
        async with pool.acquire() as ctx:
            # acquire() отдаёт ровно тот pooled-context, который помечен in_use.
            assert ctx is pool._contexts[0].context
            assert pool._contexts[0].in_use is True
            raise RuntimeError("boom")

    # Context должен быть освобождён несмотря на исключение
    assert pool._contexts[0].in_use is False
    assert pool._semaphore._value == 1  # type: ignore[attr-defined]


# === Priority 3 / 3: acquire -> cancellation -> release ===
@pytest.mark.asyncio
async def test_acquire_cancellation_releases_slot() -> None:
    """asyncio.CancelledError в body также освобождает slot."""
    pool = _make_pool_with_mock_contexts(size=1)

    with pytest.raises(asyncio.CancelledError):
        async with pool.acquire() as ctx:
            assert ctx is pool._contexts[0].context
            assert pool._contexts[0].in_use is True
            raise asyncio.CancelledError()

    assert pool._contexts[0].in_use is False
    assert pool._semaphore._value == 1  # type: ignore[attr-defined]


# === Priority 3 / дополнительно: double-acquire exhaustion ===
@pytest.mark.asyncio
async def test_double_acquire_exhausts_then_releases() -> None:
    """size=1: первый acquire OK, второй acquire ждёт освобождения."""
    pool = _make_pool_with_mock_contexts(size=1)

    async with pool.acquire() as _:
        # Пока удерживаем единственный context, второй acquire должен ждать.
        # Используем wait_for с коротким таймаутом для проверки.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(pool.acquire().__aenter__(), timeout=0.1)
    # После освобождения второго acquire должен сработать.
    async with pool.acquire() as _:
        pass


# === Priority 3 / 8: shutdown закрывает все contexts ===
@pytest.mark.asyncio
async def test_shutdown_closes_all_contexts_and_resets_started() -> None:
    """shutdown должен закрыть все contexts (защита от утечки) и сбросить _started."""
    pool = _make_pool_with_mock_contexts(size=3)

    closed: list[Any] = []

    # Подменяем context.close на запись в closed-список
    for p in pool._contexts:
        original = p.context.close

        async def tracker(_orig=original):
            closed.append(_orig)
            return await _orig()

        p.context.close = tracker

    await pool.shutdown()

    assert len(closed) == 3, f"expected 3 contexts closed, got {len(closed)}"
    assert pool._started is False
    assert len(pool._contexts) == 0  # Очищены


# === Priority 3 / bonus: двойной shutdown idempotentен ===
@pytest.mark.asyncio
async def test_shutdown_idempotent() -> None:
    """shutdown не падает при повторном вызове (idempotent)."""
    pool = _make_pool_with_mock_contexts(size=1)
    await pool.shutdown()  # первый раз
    await pool.shutdown()  # второй раз — no-op, не падает
    assert pool._started is False
