"""Тесты retry + cleanup-семантики browser launch в PlaywrightBrowserPool.

2026-10-15: добавлены ``_launch_browser_with_retry()`` (transient-crash
resilience через канонический ``core.resilience.retry.retry_async``, R-V15-8)
и ``_release_partial_resources()`` (R-V15-11 leak prevention: неудачный
startup не должен оставлять «висящий» playwright subprocess).

Тесты покрывают:

1. Успех с первой попытки — happy path не меняется;
2. Retry при transient-сбое: N попыток, затем успех;
3. Exhaustion: все попытки провалились → propagate последнего исключения;
4. ``retries=0`` → fail-fast, ровно 1 попытка;
5. Backoff экспоненциальный (base × 2^(n-1));
6. Cleanup: после исчерпания retry playwright instance остановлен;
7. Cleanup: контексты, созданные до сбоя, закрыты;
8. Pool поднимается заново после неудачного startup;
9. ``CancelledError`` не ретраится и не маскируется cleanup-ом;
10. Настройки читаются из ``rpa_settings`` (wiring test).

Реальный Chromium не используется — мок browser-launcher. Это позволяет
детерминированно проверить retry- и cleanup-семантику без реальных сбоев.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool


class _FlakyLauncher:
    """Launcher, который падает ``fail_times`` раз, затем succeeds."""

    def __init__(
        self,
        fail_times: int,
        exc: BaseException | None = None,
        context_error_after: int | None = None,
    ) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.exc = exc or RuntimeError("browser crashed (transient)")
        # Если задано — new_context() падает после N успешных вызовов
        # (эмуляция сбоя на этапе наполнения пула).
        self.context_error_after = context_error_after
        self.context_calls = 0
        self._browser: _FakeBrowser | None = None

    async def launch(self, **kwargs: Any) -> _FakeBrowser:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        self._browser = _FakeBrowser(self)
        return self._browser


class _FakeBrowser:
    """Минимальный browser-заглушка (достаточно для startup)."""

    def __init__(self, launcher: _FlakyLauncher | None = None) -> None:
        self.closed = False
        self.contexts: list[Any] = []
        self._launcher = launcher

    async def new_context(self, viewport: Any = None) -> Any:
        if self._launcher is not None:
            self._launcher.context_calls += 1
            if (
                self._launcher.context_error_after is not None
                and self._launcher.context_calls > self._launcher.context_error_after
            ):
                raise RuntimeError("new_context failed (transient)")
        ctx = _FakeContext()
        self.contexts.append(ctx)
        return ctx

    async def close(self) -> None:
        self.closed = True


class _FakeContext:
    """Минимальный context-заглушка."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakePlaywrightInstance:
    """Заглушка playwright instance: трекает вызовы ``stop()``."""

    def __init__(self, launcher: _FlakyLauncher) -> None:
        self.chromium = launcher
        self.stop_calls = 0

    async def __aenter__(self) -> _FakePlaywrightInstance:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def stop(self) -> None:
        self.stop_calls += 1


class _FakeRuntime:
    """Заглушка ``playwright.async_api``/``patchright.async_api``."""

    def __init__(self, pw_instance: _FakePlaywrightInstance) -> None:
        self._pw = pw_instance

    def async_playwright(self) -> _FakePlaywrightInstance:
        return self._pw


def _make_pool(
    monkeypatch: pytest.MonkeyPatch,
    launcher: _FlakyLauncher,
    *,
    retries: int,
    base_delay: float = 0.0,
    size: int = 1,
) -> PlaywrightBrowserPool:
    """Создаёт pool с подменённым launcher и заданными retry-параметрами.

    Returns:
        Pool; playwright instance доступен как ``pool._fake_pw``.
    """
    pool = PlaywrightBrowserPool(
        size=size, prefer_patchright=False, browser_kind="chromium", headless=True
    )
    monkeypatch.setattr(pool, "_launch_max_retries", retries)
    monkeypatch.setattr(pool, "_launch_retry_base", base_delay)

    pw_instance = _FakePlaywrightInstance(launcher)
    pool._fake_pw = pw_instance  # type: ignore[attr-defined]

    async def _fake_import_runtime() -> Any:
        return _FakeRuntime(pw_instance)

    monkeypatch.setattr(pool, "_import_runtime", _fake_import_runtime)
    return pool


class TestBrowserLaunchRetry:
    """Retry-семантика browser launch."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Happy path: 1 вызов launch, старт без retry."""
        launcher = _FlakyLauncher(fail_times=0)
        pool = _make_pool(monkeypatch, launcher, retries=2)

        await pool.startup()

        assert launcher.calls == 1, (
            f"Happy path должен делать ровно 1 вызов, сделал {launcher.calls}"
        )
        assert pool.is_started
        assert len(pool._contexts) == 1
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_transient_failures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transient-сбой → retry → успех."""
        launcher = _FlakyLauncher(fail_times=2)
        pool = _make_pool(monkeypatch, launcher, retries=3)

        await pool.startup()

        assert launcher.calls == 3, (
            f"Ожидалось 3 попытки (2 fail + 1 success), было {launcher.calls}"
        )
        assert pool.is_started
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_retry_exhausted_propagates_last_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Все попытки провалились → propagate последнего исключения."""
        boom = RuntimeError("always broken")
        launcher = _FlakyLauncher(fail_times=99, exc=boom)
        pool = _make_pool(monkeypatch, launcher, retries=2)

        with pytest.raises(RuntimeError, match="always broken"):
            await pool.startup()

        assert launcher.calls == 3, (
            f"Ожидалось 3 попытки (retries=2 + initial), было {launcher.calls}"
        )
        assert not pool.is_started, "pool не должен быть started после провала"

    @pytest.mark.asyncio
    async def test_retries_zero_is_fail_fast(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retries=0 → ровно 1 попытка, без retry."""
        launcher = _FlakyLauncher(fail_times=99)
        pool = _make_pool(monkeypatch, launcher, retries=0)

        with pytest.raises(RuntimeError, match="browser crashed"):
            await pool.startup()

        assert launcher.calls == 1, (
            f"retries=0 должен означать 1 попытку, было {launcher.calls}"
        )

    @pytest.mark.asyncio
    async def test_backoff_is_exponential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Задержки между попытками: base × 2^(n-1)."""
        launcher = _FlakyLauncher(fail_times=99)
        pool = _make_pool(monkeypatch, launcher, retries=3, base_delay=0.01)

        delays: list[float] = []
        real_sleep = asyncio.sleep

        async def _spy_sleep(delay: float, *a: Any, **kw: Any) -> None:
            delays.append(delay)
            # Не ждём реально — тест проверяет только сами значения.
            await real_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", _spy_sleep)

        with pytest.raises(RuntimeError):
            await pool.startup()

        # 3 retry-попытки → 3 задержки: 0.01, 0.02, 0.04
        assert delays == [0.01, 0.02, 0.04], (
            f"Exponential backoff нарушен: {delays} != [0.01, 0.02, 0.04]"
        )

    @pytest.mark.asyncio
    async def test_cancellation_is_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CancelledError не ретраится: 1 попытка, отмена пробрасывается."""
        launcher = _FlakyLauncher(fail_times=99, exc=asyncio.CancelledError())
        pool = _make_pool(monkeypatch, launcher, retries=3)

        with pytest.raises(asyncio.CancelledError):
            await pool.startup()

        assert launcher.calls == 1, (
            f"Отмена не должна ретраиться, было {launcher.calls} попыток"
        )


class TestPartialStartupCleanup:
    """R-V15-11: неудачный startup не оставляет «висящих» ресурсов."""

    @pytest.mark.asyncio
    async def test_exhausted_launch_stops_playwright_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """После исчерпания retry playwright instance остановлен."""
        launcher = _FlakyLauncher(fail_times=99)
        pool = _make_pool(monkeypatch, launcher, retries=2)

        with pytest.raises(RuntimeError):
            await pool.startup()

        pw = pool._fake_pw  # type: ignore[attr-defined]
        assert pw.stop_calls == 1, "playwright subprocess должен быть остановлен"
        assert pool._pw_instance is None, "_pw_instance обязан быть сброшен"
        assert pool._browser is None, "_browser обязан быть сброшен"
        assert pool._contexts == [], "_contexts обязан быть пуст"

    @pytest.mark.asyncio
    async def test_new_context_failure_closes_browser_and_contexts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сбой new_context() закрывает browser и уже созданные контексты."""
        launcher = _FlakyLauncher(fail_times=0, context_error_after=1)
        pool = _make_pool(monkeypatch, launcher, retries=0, size=3)

        with pytest.raises(RuntimeError, match="new_context failed"):
            await pool.startup()

        browser = launcher._browser
        assert browser is not None, "browser был создан"
        assert browser.closed, "browser должен быть закрыт при частичном startup"
        assert browser.contexts, "ожидался хотя бы один созданный контекст"
        assert all(c.closed for c in browser.contexts), (
            "все контексты, созданные до сбоя, должны быть закрыты"
        )
        assert pool._contexts == []
        assert pool._pw_instance is None
        pw = pool._fake_pw  # type: ignore[attr-defined]
        assert pw.stop_calls == 1, "playwright instance должен быть остановлен"

    @pytest.mark.asyncio
    async def test_pool_restarts_after_failed_startup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """После неудачного startup pool поднимается заново."""
        launcher = _FlakyLauncher(fail_times=2)
        pool = _make_pool(monkeypatch, launcher, retries=1)

        with pytest.raises(RuntimeError):
            await pool.startup()
        assert not pool.is_started

        await pool.startup()

        assert pool.is_started, "повторный startup должен succeed"
        assert len(pool._contexts) == 1
        assert launcher.calls == 3, "2 fail + 1 success на второй попытке"
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent_after_failed_startup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shutdown() после провала — no-op и не падает."""
        launcher = _FlakyLauncher(fail_times=99)
        pool = _make_pool(monkeypatch, launcher, retries=0)

        with pytest.raises(RuntimeError):
            await pool.startup()

        await pool.shutdown()  # не должно бросать
        pw = pool._fake_pw  # type: ignore[attr-defined]
        assert pw.stop_calls == 1, "shutdown не должен stop'ать второй раз"


class TestRetryConfigWiring:
    """Настройки retry приходят из rpa_settings."""

    def test_defaults_are_defined(self) -> None:
        """rpa_settings содержит оба новых поля с sane-дефолтами."""
        from src.backend.core.config.services.rpa import rpa_settings

        assert rpa_settings.browser_launch_max_retries == 2
        assert rpa_settings.browser_launch_retry_base_seconds == 0.5

    @pytest.mark.asyncio
    async def test_pool_reads_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pool наследует значения из rpa_settings при инициализации."""
        from src.backend.core.config.services.rpa import rpa_settings

        monkeypatch.setattr(
            rpa_settings, "browser_launch_max_retries", 5, raising=False
        )
        monkeypatch.setattr(
            rpa_settings, "browser_launch_retry_base_seconds", 1.5, raising=False
        )

        pool = PlaywrightBrowserPool(size=1, prefer_patchright=False, headless=True)
        assert pool._launch_max_retries == 5
        assert pool._launch_retry_base == 1.5
