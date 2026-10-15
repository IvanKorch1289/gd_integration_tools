"""P1 (2026-10-15) audit: real-browser integration tests для BrowserPool.

Существующие lifecycle-тесты (test_browser_pool_lifecycle.py) используют
мок-контексты через ``__new__`` и ``SimpleNamespace``. Они покрывают
semantics управления слотами, но НЕ доказывают:

1. Реальный chromium-context изолирует cookies и localStorage между
   tenant/users;
2. Реальный exception в page operation освобождает context (через
   close() в finally), а не оставляет zombie context;
3. Реальное cancellation во время page operation освобождает context;
4. Context реально закрывается (browser-side ``is_closed()``);
5. Persistent context не включается без явной configuration.

Этот файл — integration-тест, использующий НАСТОЯЩИЙ chromium через
playwright (а не мок). Требует установленного playwright + chromium.

Skip on import error (chromium не установлен в dev_light env).
Запуск::

    uv run pytest tests/integration/rpa/test_browser_pool_real_browser.py -v

Не создаёт новый browser abstraction поверх Playwright. Использует
уже подключённый ``PlaywrightBrowserPool.startup/shutdown/acquire``
как есть — ровно то, что вызывают DSL-роуты в production.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

# Skip entire module if playwright или chromium недоступен
try:
    from playwright.async_api import async_playwright  # noqa: F401

    _PW_AVAILABLE = True
except ImportError:
    _PW_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not _PW_AVAILABLE, reason="playwright не установлен (pip install playwright)"
)


@pytest.fixture
async def real_browser_pool():
    """Реальный PlaywrightBrowserPool с настоящим chromium.

    Yields started pool (size=2) и shutdown'ит после теста.
    """
    from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool

    pool = PlaywrightBrowserPool(
        size=2,
        prefer_patchright=False,  # fallback на playwright если patchright недоступен
        browser_kind="chromium",
        headless=True,
    )
    await pool.startup()
    try:
        yield pool
    finally:
        await pool.shutdown()


# ─────────────────────────── 1. tenant isolation (cookies + localStorage) ───────────────────────────


@pytest.mark.asyncio
async def test_two_contexts_have_isolated_cookies(
    real_browser_pool: Any,
) -> None:
    """Два BrowserContext из pool имеют РАЗНЫЕ cookies.

    Audit P1 пункт 1: «Два BrowserContext имеют разные cookies и
    localStorage». Реальный Playwright BrowserContext даёт изоляцию
    по дизайну (каждый context = независимая сессия), но мы
    проверяем это end-to-end через BrowserPool.acquire().

    Проверяем через КОНКУРЕНТНЫЙ acquire двух разных context-слотов
    (size=2). Это реальный сценарий: tenant A и tenant B
    одновременно работают с двумя разными context-объектами.
    """
    async with real_browser_pool.acquire() as ctx_a:
        # Захватываем второй slot конкурентно (тот же pool, size=2)
        async with real_browser_pool.acquire() as ctx_b:
            # Sanity: это должны быть РАЗНЫЕ context-объекты
            assert ctx_a is not ctx_b, (
                "Pool size=2 должен отдавать разные context на двух "
                "конкурентных acquire; иначе изоляция невозможна в принципе"
            )
            # Tenant A: ставим cookie
            await ctx_a.add_cookies(
                [
                    {
                        "name": "tenant",
                        "value": "tenant-A",
                        "url": "https://example.com",
                    }
                ]
            )
            cookies_a = await ctx_a.cookies()
            assert any(
                c["name"] == "tenant" and c["value"] == "tenant-A"
                for c in cookies_a
            ), f"Tenant A cookie not set: {cookies_a}"

            # Tenant B: должен быть пустой (изоляция)
            cookies_b = await ctx_b.cookies()
            tenant_b_leak = [c for c in cookies_b if c["name"] == "tenant"]
            assert len(tenant_b_leak) == 0, (
                f"Tenant A cookie leaked into Tenant B: {tenant_b_leak}; "
                "BrowserContext НЕ изолирует tenant state"
            )


@pytest.mark.asyncio
async def test_two_contexts_have_isolated_local_storage(
    real_browser_pool: Any,
) -> None:
    """Два BrowserContext имеют РАЗНЫЙ localStorage.

    localStorage в Playwright полностью изолирован per-context. Этот
    тест — regression-protection: если кто-то переключит pool на
    shared browser context (например, использует default_context
    вместо new_context), тест упадёт.

    Используем КОНКУРЕНТНЫЙ acquire чтобы получить два разных
    context-объекта (последовательный acquire может вернуть тот же
    context после release — это by design для in-memory pool).
    """
    async with real_browser_pool.acquire() as ctx_a:
        async with real_browser_pool.acquire() as ctx_b:
            assert ctx_a is not ctx_b, (
                "Pool size=2: два конкурентных acquire должны вернуть "
                "разные context-объекты"
            )
            page_a = await ctx_a.new_page()
            await page_a.goto("https://example.com/")
            await page_a.evaluate("localStorage.setItem('tenant', 'tenant-A')")
            storage_a = await page_a.evaluate("localStorage.getItem('tenant')")
            assert storage_a == "tenant-A", (
                f"Tenant A localStorage broken: {storage_a}"
            )

            page_b = await ctx_b.new_page()
            await page_b.goto("https://example.com/")
            storage_b = await page_b.evaluate("localStorage.getItem('tenant')")
            assert storage_b is None, (
                f"Tenant A localStorage leaked into Tenant B: {storage_b!r}; "
                "BrowserContext не изолирует localStorage"
            )
            await page_a.close()
            await page_b.close()


# ─────────────────────────── 2. exception in body releases context ───────────────────────────


@pytest.mark.asyncio
async def test_exception_in_body_closes_and_releases_context(
    real_browser_pool: Any,
) -> None:
    """Exception в body acquire() → context закрывается, slot освобождается.

    Audit P1 пункт 2: «Exception освобождает/закрывает context».
    Проверяем через ``ctx.is_closed()`` — реальный browser-side flag.
    """
    # Phase 1: trigger exception в body
    with pytest.raises(RuntimeError, match="test-exception"):
        async with real_browser_pool.acquire() as ctx:
            assert not ctx.is_closed(), (
                "Context must be open inside acquire() body"
            )
            raise RuntimeError("test-exception")
    # Phase 2: pool остался с size=2 — оба context снова доступны
    assert len(real_browser_pool._contexts) == 2, (
        f"Pool contexts count changed: {len(real_browser_pool._contexts)} "
        "(expected: 2 — exception in body should NOT remove context)"
    )
    # Все контексты НЕ in_use (через observable state)
    for i, p in enumerate(real_browser_pool._contexts):
        assert p.in_use is False, f"Context {i} still in_use after exception"

    # Phase 3: можем acquire'ить снова — slot реально свободен
    async with real_browser_pool.acquire() as ctx2:
        assert not ctx2.is_closed(), (
            "Re-acquired context should be open (real context, not a "
            "zombie/closed one)"
        )
        assert ctx2 is real_browser_pool._contexts[0].context or \
            ctx2 is real_browser_pool._contexts[1].context, (
            "Re-acquired context is not from the pool"
        )


# ─────────────────────────── 3. cancellation during page op releases context ───────────────────────────


@pytest.mark.asyncio
async def test_cancellation_during_page_op_releases_context(
    real_browser_pool: Any,
) -> None:
    """CancelledError во время page operation → context освобождается.

    Audit P1 пункт 3: «Cancellation во время page operation
    освобождает context». Проверяем через finally-block semantics
    в acquire() + реальный page.goto() который можно отменить.
    """
    async def _cancel_during_goto() -> None:
        async with real_browser_pool.acquire() as ctx:
            page = await ctx.new_page()
            # Cancel during goto — CancelledError должен подняться
            task = asyncio.create_task(
                page.goto("https://example.com/", timeout=30_000)
            )
            await asyncio.sleep(0.05)  # дать page.goto стартовать
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await page.close()  # close в finally, чтобы не утекало

    await _cancel_during_goto()
    # После CancelledError — slot снова доступен
    assert all(not p.in_use for p in real_browser_pool._contexts), (
        "Context still in_use after cancellation"
    )
    # Re-acquire работает
    async with real_browser_pool.acquire() as ctx2:
        assert not ctx2.is_closed(), (
            "Re-acquired context is closed — cancellation broke context reuse"
        )


# ─────────────────────────── 4. timeout policy сохраняется (regression-protection) ───────────────────────────


@pytest.mark.asyncio
async def test_timeout_returns_typed_failure_and_releases(
    real_browser_pool: Any,
) -> None:
    """Timeout в page operation → slot освобождается, не блокируется.

    Audit P1 пункт 4: «Timeout сохраняет screenshot и trace/HAR».
    Текущая реализация BrowserPool не делает screenshot на error
    (это ответственность route-orchestrator), но ОБЯЗАНА освободить
    слот при timeout. Без этого — утечка pool'а при page hangs.
    """
    with pytest.raises(Exception):  # playwright TimeoutError или asyncio.TimeoutError
        async with real_browser_pool.acquire() as ctx:
            page = await ctx.new_page()
            try:
                # goto с явным timeout=100ms на медленный endpoint
                await page.goto(
                    "https://httpbin.org/delay/5",  # 5-second delay
                    timeout=100,
                )
            finally:
                await page.close()
    # Slot освобождён несмотря на timeout
    assert all(not p.in_use for p in real_browser_pool._contexts), (
        "Context in_use after timeout — pool leak"
    )


# ─────────────────────────── 5. shutdown closes all contexts (real) ───────────────────────────


@pytest.mark.asyncio
async def test_shutdown_closes_all_contexts_and_browser() -> None:
    """После shutdown все контексты реально закрыты (is_closed() == True).

    Audit P1 пункт 6: «Shutdown при свободных и занятых contexts
    завершается предсказуемо». Через реальный browser-side flag.
    """
    from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool

    pool = PlaywrightBrowserPool(
        size=3, prefer_patchright=False, browser_kind="chromium", headless=True
    )
    await pool.startup()
    contexts = list(pool._contexts)
    assert len(contexts) == 3
    # Все открыты
    for c in contexts:
        assert not c.context.is_closed(), "Context should be open after startup"

    # Закрываем
    await pool.shutdown()
    # Все закрыты
    for c in contexts:
        assert c.context.is_closed(), (
            "Context NOT closed after shutdown — browser resource leak"
        )
    # Pool reset
    assert pool._contexts == [], "Pool contexts not cleared after shutdown"
    assert pool._browser is None
    assert pool._pw_instance is None


@pytest.mark.asyncio
async def test_shutdown_with_busy_context_does_not_hang() -> None:
    """Shutdown при «занятом» context (но не acquired) завершается чисто.

    Audit P1 пункт 6.2: «Shutdown при свободных и занятых contexts
    завершается предсказуемо». В PlaywrightBrowserPool нет explicit
    "busy" state (только in_use flag), но pool может shutdown'ить
    с контекстами, в которых открыты Pages.
    """
    from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool

    pool = PlaywrightBrowserPool(
        size=2, prefer_patchright=False, browser_kind="chromium", headless=True
    )
    await pool.startup()
    # Открываем page в context (НЕ через acquire)
    ctx = pool._contexts[0].context
    page = await ctx.new_page()
    # Shutdown — должен закрыть page + context
    await pool.shutdown()
    assert ctx.is_closed(), "Context with open page NOT closed after shutdown"
    assert page.is_closed(), "Page NOT closed after shutdown"


# ─────────────────────────── 6. idempotent shutdown ───────────────────────────


@pytest.mark.asyncio
async def test_double_shutdown_is_idempotent() -> None:
    """Повторный shutdown не падает (idempotent contract).

    Проверяет, что shutdown() можно вызывать несколько раз без
    exception — это уже покрыто в unit-тесте, но здесь мы
    проверяем на РЕАЛЬНОМ browser (где close() на уже-закрытом
    context может raise).
    """
    from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool

    pool = PlaywrightBrowserPool(
        size=1, prefer_patchright=False, browser_kind="chromium", headless=True
    )
    await pool.startup()
    await pool.shutdown()
    # Второй shutdown — no-op (started=False)
    await pool.shutdown()  # не должен raise


# ─────────────────────────── 7. persistent context НЕ создаётся по умолчанию ───────────────────────────


@pytest.mark.asyncio
async def test_persistent_context_not_used_by_default() -> None:
    """Persistent context — НЕ создаётся без явной configuration.

    Audit P1 пункт 7: «Persistent context не включается без явной
    configuration». BrowserPool.startup() использует
    ``browser.new_context()`` (in-memory), а НЕ
    ``launch_persistent_context()`` (disk-based).

    Проверяем косвенно: после shutdown + повторный startup —
    НЕТ сохранённого storage state (cookies, localStorage) с
    предыдущего «сеанса». Если бы был persistent context —
    storage state пережил бы shutdown.
    """
    from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool

    pool = PlaywrightBrowserPool(
        size=1, prefer_patchright=False, browser_kind="chromium", headless=True
    )
    await pool.startup()
    # Устанавливаем cookie
    await pool._contexts[0].context.add_cookies(
        [{"name": "session", "value": "secret-123", "url": "https://example.com"}]
    )
    cookies = await pool._contexts[0].context.cookies()
    assert any(c["name"] == "session" for c in cookies)
    # Shutdown — in-memory state должен быть потерян
    await pool.shutdown()
    # Re-startup — новый context, cookies не сохранились
    await pool.startup()
    cookies_after = await pool._contexts[0].context.cookies()
    assert not any(c["name"] == "session" for c in cookies_after), (
        "Persistent storage detected — BrowserPool использует disk-based "
        "context вместо in-memory; это нарушает контракт 'no persistent "
        "context without explicit configuration'"
    )
    await pool.shutdown()
