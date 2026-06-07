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
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


__all__ = ("PlaywrightBrowserPool",)

_logger = get_logger(__name__)


@dataclass
class _PooledContext:
    """Wrapper над playwright/patchright BrowserContext."""

    context: Any
    in_use: bool = False
    created_at: float = field(default_factory=lambda: 0.0)


class PlaywrightBrowserPool:
    """Async pool из N браузерных контекстов patchright/playwright.

    Args:
        size: Количество предсозданных контекстов (default 2).
        prefer_patchright: ``True`` — пытаться импортировать patchright
            (anti-detection); ``False`` — сразу playwright.
        browser_kind: ``"chromium"`` / ``"firefox"`` / ``"webkit"``.
        headless: ``True`` для CI / production; ``False`` для локальной
            отладки.
        viewport: Размер viewport ``{"width": ..., "height": ...}``;
            ``None`` — default 1280×720.
    """

    def __init__(
        self,
        *,
        size: int = 2,
        prefer_patchright: bool = True,
        browser_kind: str = "chromium",
        headless: bool = True,
        viewport: dict[str, int] | None = None,
    ) -> None:
        if size < 1:
            raise ValueError(f"size должен быть >= 1, получено {size}")
        self._size = size
        self._prefer_patchright = prefer_patchright
        self._browser_kind = browser_kind
        self._headless = headless
        self._viewport = viewport or {"width": 1280, "height": 720}

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
        """
        if self._started:
            return
        async with self._lock:
            if self._started:
                return

            pw_module = await self._import_runtime()
            self._pw_instance = await pw_module.async_playwright().__aenter__()
            launcher = getattr(self._pw_instance, self._browser_kind)
            self._browser = await launcher.launch(headless=self._headless)

            for _ in range(self._size):
                ctx = await self._browser.new_context(viewport=self._viewport)
                self._contexts.append(_PooledContext(context=ctx))

            self._started = True
            _logger.info(
                "PlaywrightBrowserPool started: size=%d kind=%s patchright=%s",
                self._size,
                self._browser_kind,
                self._prefer_patchright,
            )

    async def shutdown(self) -> None:
        """Закрывает контексты + browser + playwright instance."""
        if not self._started:
            return
        async with self._lock:
            for pooled in self._contexts:
                try:
                    await pooled.context.close()
                except Exception as exc:
                    _logger.debug("PlaywrightBrowserPool: close failed: %s", exc)
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as exc:
                    _logger.debug("PlaywrightBrowserPool: close failed: %s", exc)
            if self._pw_instance is not None:
                try:
                    await self._pw_instance.stop()
                except Exception as exc:
                    _logger.debug("PlaywrightBrowserPool: close failed: %s", exc)
            self._contexts.clear()
            self._browser = None
            self._pw_instance = None
            self._started = False
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
            from playwright import async_api

            return async_api
        except ImportError as exc:
            raise RuntimeError(
                "Ни patchright, ни playwright не установлены; "
                "установите: uv sync --extra rpa"
            ) from exc
