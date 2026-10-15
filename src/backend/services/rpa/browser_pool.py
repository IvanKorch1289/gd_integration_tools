"""PlaywrightBrowserPool — worker-pool браузерных контекстов patchright.

Wave: ``[wave:s8/k3-rpa-universal-stage1]``. Поддерживает patchright (anti-
detection fork playwright) и обычный playwright как fallback. Контексты
переиспользуются между DSL-шагами одного route.

Lifecycle:
    1. Создание pool на startup (lifespan) с N контекстами;
    2. ``acquire()`` — async with — получает свободный context;
    3. ``release()`` (через ``__aexit__``) — возвращает context в pool;
    4. ``shutdown()`` — закрывает все контексты + browser instance.

Threading:
    Pool — async-safe (asyncio.Semaphore + Lock). Один экземпляр
    обслуживает все DSL-routes процесса.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.resilience.retry import retry_async

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


__all__ = ("PlaywrightBrowserPool",)

_logger = get_logger(__name__)

# Playwright оборачивает ЛЮБОЙ сбой запуска браузера в ``Error`` (подкласс
# ``Exception``): OOM killer, нехватка /dev/shm и «нет бинаря браузера»
# неразличимы по типу. Поэтому retry-предикат — ``Exception``.
# ``BaseException``-классы (asyncio.CancelledError, KeyboardInterrupt) под
# него не попадают и пробрасываются немедленно — это критично для shutdown.
_BROWSER_LAUNCH_RETRYABLE: tuple[type[BaseException], ...] = (Exception,)


@dataclass
class _PooledContext:
    """Wrapper над playwright/patchright BrowserContext."""

    context: Any
    in_use: bool = False
    created_at: float = field(default_factory=lambda: 0.0)


class PlaywrightBrowserPool:
    """Async pool из N браузерных контекстов patchright/playwright.

    Args:
        size: Количество предсозданных контекстов. Cycle 40: defaults to
            ``rpa_settings.browser_pool_size`` if not explicitly provided.
        prefer_patchright: ``True`` — пытаться импортировать patchright
            (anti-detection); ``False`` — сразу playwright.
        browser_kind: ``"chromium"`` / ``"firefox"`` / ``"webkit"``.
        headless: ``True`` для CI / production; ``False`` для локальной
            отладки. Cycle 40: defaults to ``rpa_settings.browser_headless``.
        viewport: Размер viewport ``{"width": ..., "height": ...}``;
            ``None`` — default 1280×720.

    """

    def __init__(
        self,
        *,
        size: int | None = None,
        prefer_patchright: bool = True,
        browser_kind: str = "chromium",
        headless: bool | None = None,
        viewport: dict[str, int] | None = None,
    ) -> None:
        # Cycle 40: wire rpa_settings.browser_pool_size / .browser_headless
        # (previously dead config fields). Lazy import to avoid circular
        # dependencies at module-load time.
        from src.backend.core.config.services.rpa import rpa_settings

        if size is None:
            size = rpa_settings.browser_pool_size
        if headless is None:
            headless = rpa_settings.browser_headless

        if size < 1:
            raise ValueError(f"size должен быть >= 1, получено {size}")
        self._size = size
        self._prefer_patchright = prefer_patchright
        self._browser_kind = browser_kind
        self._headless = headless
        self._viewport = viewport or {"width": 1280, "height": 720}
        # 2026-10-15: retry для browser launch (transient-crash resilience),
        # конфигурируется через rpa_settings. ``browser_launch_max_retries``
        # — число ПОВТОРОВ (не попыток): 0 = fail-fast (1 попытка),
        # default 2 = 3 попытки. Реализация — канонический
        # ``core.resilience.retry.retry_async`` (tenacity, R-V15-8).
        self._launch_max_retries = rpa_settings.browser_launch_max_retries
        self._launch_retry_base = rpa_settings.browser_launch_retry_base_seconds

        self._pw_instance: Any = None
        self._browser: Any = None
        self._contexts: list[_PooledContext] = []
        self._semaphore = asyncio.Semaphore(size)
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def size(self) -> int:
        """Размер pool'а."""
        return self._size

    @property
    def is_started(self) -> bool:
        """Состояние lifecycle."""
        return self._started

    async def startup(self) -> None:
        """Инициализирует playwright/patchright и создаёт N контекстов.

        Idempotent: повторный вызов — no-op.

        При любом сбое (включая исчерпание launch-retry) частично созданные
        ресурсы освобождаются через :meth:`_release_partial_resources`,
        иначе остался бы «висящий» playwright subprocess: ``shutdown()``
        при ``_started=False`` — no-op, и утечку не закрыть (R-V15-11).

        Raises:
            BaseException: исходная ошибка startup; ресурсы к этому моменту
                уже освобождены, pool остаётся в исходном состоянии.
        """
        if self._started:
            return
        async with self._lock:
            if self._started:
                return

            pw_module = await self._import_runtime()
            self._pw_instance = await pw_module.async_playwright().__aenter__()
            try:
                self._browser = await self._launch_browser_with_retry(self._pw_instance)

                for _ in range(self._size):
                    ctx = await self._browser.new_context(viewport=self._viewport)
                    self._contexts.append(_PooledContext(context=ctx))
            except BaseException:
                await self._release_partial_resources()
                raise

            self._started = True
            _logger.info(
                "PlaywrightBrowserPool started: size=%d kind=%s patchright=%s "
                "launch_retries=%d",
                self._size,
                self._browser_kind,
                self._prefer_patchright,
                self._launch_max_retries,
            )

    async def _launch_browser_with_retry(self, pw_instance: Any) -> Any:
        """Запускает browser с exponential-backoff retry.

        2026-10-15: transient-crash resilience. Chromium может упасть при
        старте из-за OOM killer, нехватки shm, или редких race-условий
        при параллельном запуске нескольких browser-процессов. По типу
        эти ошибки неотличимы от permanent-сбоев, поэтому решение
        принимает tenacity-обёртка :func:`core.resilience.retry.retry_async`
        (канонический retry проекта, R-V15-8), а не ручной цикл.

        Retry применяется только к ``launcher.launch()``; ``__aenter__``
        на playwright-instance не ретраится (он создаёт subprocess, и
        его падение — уже другая категория ошибок).

        Args:
            pw_instance: Запущенный экземпляр ``async_playwright()``.

        Returns:
            Запущенный browser instance.

        Raises:
            Exception: последнее исключение ``launch()``, если все попытки
                исчерпаны (``retry_async(reraise=True)`` не оборачивает
                его в ``RetryError``).
        """
        launcher = getattr(pw_instance, self._browser_kind)
        max_attempts = self._launch_max_retries + 1
        # Кап для wait_exponential: последний фактический шаг backoff.
        max_backoff = self._launch_retry_base * 2 ** max(
            self._launch_max_retries - 1, 0
        )
        attempts_used = 0

        async def _launch_once() -> Any:
            """Одна попытка ``launcher.launch()`` с диагностическим логом."""
            nonlocal attempts_used
            attempts_used += 1
            try:
                return await launcher.launch(headless=self._headless)
            except Exception as exc:
                _logger.warning(
                    "PlaywrightBrowserPool: browser launch failed "
                    "(attempt %d/%d): %s: %s",
                    attempts_used,
                    max_attempts,
                    type(exc).__name__,
                    exc,
                )
                raise

        browser: Any = await retry_async(
            _launch_once,
            max_attempts=max_attempts,
            base_delay=self._launch_retry_base,
            max_delay=max_backoff,
            retryable=_BROWSER_LAUNCH_RETRYABLE,
            op=f"browser_launch[{self._browser_kind}]",
        )
        if attempts_used > 1:
            _logger.info(
                "PlaywrightBrowserPool: browser launched after %d attempt(s)",
                attempts_used,
            )
        return browser

    async def _release_partial_resources(self) -> None:
        """Освобождает ресурсы неудачного (частичного) startup.

        Best-effort: ошибка закрытия одного ресурса не должна маскировать
        исходное исключение, поэтому каждая операция в own try/except
        с debug-логом. Поля сбрасываются в исходное состояние, чтобы
        следующий ``startup()`` прошёл чистый цикл.

        Вызывается из ``startup()`` (путь ошибки) и из ``shutdown()``
        (нормальный путь), поэтому не зависит от ``_started``.
        """
        for pooled in self._contexts:
            try:
                await pooled.context.close()
            except Exception as exc:
                _logger.debug("PlaywrightBrowserPool: close failed: %s", exc)
        self._contexts.clear()
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                _logger.debug("PlaywrightBrowserPool: close failed: %s", exc)
            self._browser = None
        if self._pw_instance is not None:
            try:
                await self._pw_instance.stop()
            except Exception as exc:
                _logger.debug("PlaywrightBrowserPool: close failed: %s", exc)
            self._pw_instance = None
        self._started = False

    async def shutdown(self) -> None:
        """Закрывает контексты + browser + playwright instance."""
        if not self._started:
            return
        async with self._lock:
            await self._release_partial_resources()
            _logger.info("PlaywrightBrowserPool shutdown complete")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        """Возвращает свободный BrowserContext (async context manager).

        При исчерпании pool'а блокирует на ``Semaphore`` до освобождения.
        """
        if not self._started:
            await self.startup()
        await self._semaphore.acquire()
        pooled: _PooledContext | None = None
        try:
            async with self._lock:
                for p in self._contexts:
                    if not p.in_use:
                        p.in_use = True
                        pooled = p
                        break
            if pooled is None:
                # Безопасный fallback (теоретически Semaphore не должен
                # пропустить сюда, но если pool пересоздан — создаём ad-hoc).
                pooled = _PooledContext(
                    context=await self._browser.new_context(viewport=self._viewport),
                    in_use=True,
                )
                self._contexts.append(pooled)
            yield pooled.context
        finally:
            if pooled is not None:
                pooled.in_use = False
            self._semaphore.release()

    async def _import_runtime(self) -> Any:
        """Lazy-import patchright (preferred) или playwright (fallback)."""
        if self._prefer_patchright:
            try:
                from patchright import async_api  # type: ignore[import-not-found]

                return async_api
            except ImportError:
                _logger.warning(
                    "patchright недоступен, fallback на playwright; "
                    "установите: uv sync --extra rpa"
                )
        try:
            from playwright import async_api as playwright_async_api

            return playwright_async_api
        except ImportError as exc:
            raise RuntimeError(
                "Ни patchright, ни playwright не установлены; "
                "установите: uv sync --extra rpa"
            ) from exc
