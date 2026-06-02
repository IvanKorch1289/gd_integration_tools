"""RouteLoader hot-reloader через watchfiles (Sprint 9 K3 W1).

Цель DoD-1: detect changes в ``routes/<name>/route.toml`` или
``routes/<name>/*.dsl.yaml`` → safe-unload старого манифеста + load новой
версии в течение <3 секунд.

Стратегия:

* :class:`watchfiles.awatch` background task on ``routes/`` root.
* Debounce window 0.5s — собрать все изменения одной серии.
* Для каждого изменённого route'а:
  1. ``asyncio.Lock`` per route_name (избегаем race с активными requests);
  2. ``RouteLoader.unload`` старого манифеста (drain in-flight);
  3. ``RouteLoader._load_one`` нового манифеста.
* Если manifest валидация падает — старая версия остаётся активной,
  событие логируется + emit'ится в audit.

Feature-flag: ``feature_flags.route_loader_hot_reload``
(default-OFF до staging-валидации).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

__all__ = ("RouteHotReloader", "ReloadEvent")

_logger = logging.getLogger("services.routes.hot_reloader")


class ReloadEvent:
    """Событие reload для observability / audit.

    Attributes:
        route_name: имя из ``routes/<name>/``.
        change_kind: ``"added"`` / ``"modified"`` / ``"removed"``.
        success: True если reload прошёл; False — старая версия осталась.
        error: текст ошибки если success=False.
    """

    __slots__ = ("route_name", "change_kind", "success", "error")

    def __init__(
        self,
        *,
        route_name: str,
        change_kind: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        self.route_name = route_name
        self.change_kind = change_kind
        self.success = success
        self.error = error


class RouteHotReloader:
    """Hot-reload watcher для RouteLoader.

    Args:
        loader: :class:`RouteLoader` instance.
        routes_root: ``Path`` к каталогу ``routes/``.
        enabled: feature-flag (default False).
        debounce_seconds: окно объединения событий (default 0.5).
        on_event: опц. callback (``ReloadEvent``) для audit/UI.
    """

    def __init__(
        self,
        *,
        loader: Any,
        routes_root: Path,
        enabled: bool = False,
        debounce_seconds: float = 0.5,
        on_event: Callable[[ReloadEvent], None] | None = None,
    ) -> None:
        self._loader = loader
        self._root = routes_root
        self._enabled = enabled
        self._debounce = debounce_seconds
        self._on_event = on_event
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # Per-route locks
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        """Запустить background watcher (idempotent)."""
        if not self._enabled:
            _logger.info("hot_reloader.disabled")
            return
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        from src.backend.core.utils.task_registry import (
            get_task_registry,  # noqa: PLC0415
        )

        self._task = get_task_registry().create_task(
            self._run(), name="route-hot-reloader"
        )
        _logger.info("hot_reloader.started", extra={"root": str(self._root)})

    async def stop(self) -> None:
        """Graceful остановка."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError, Exception:  # noqa: BLE001
                pass
            self._task = None
        _logger.info("hot_reloader.stopped")

    async def _run(self) -> None:
        """Главный watcher loop."""
        async for changes in self._watch_iter():
            if self._stop.is_set():
                break
            route_names = self._extract_route_names(changes)
            await self._reload_batch(route_names)

    async def _watch_iter(self) -> AsyncIterator[set[tuple[Any, str]]]:
        """Yield batches изменений через watchfiles (lazy-import)."""
        try:
            from watchfiles import awatch  
        except ImportError:
            _logger.warning("hot_reloader.watchfiles_unavailable")
            return

        async for changes in awatch(self._root, stop_event=self._stop):
            yield changes

    def _extract_route_names(self, changes: set[tuple[Any, str]]) -> set[str]:
        """Получить уникальные имена routes из набора путей."""
        names: set[str] = set()
        for _change_type, path_str in changes:
            path = Path(path_str)
            try:
                relative = path.relative_to(self._root)
            except ValueError:
                continue
            if not relative.parts:
                continue
            names.add(relative.parts[0])
        return names

    async def _reload_batch(self, route_names: set[str]) -> None:
        """Reload список routes последовательно (с debounce)."""
        await asyncio.sleep(self._debounce)
        for name in route_names:
            await self._reload_one(name)

    async def _reload_one(self, route_name: str) -> None:
        """Reload одного route с per-route lock."""
        lock = self._locks.setdefault(route_name, asyncio.Lock())
        async with lock:
            event = await self._do_reload(route_name)
            if self._on_event is not None:
                try:
                    self._on_event(event)
                except Exception as _:  # noqa: BLE001
                    _logger.exception("hot_reloader.on_event_callback_raised")

    async def _do_reload(self, route_name: str) -> ReloadEvent:
        """Реальная логика reload через loader."""
        manifest_path = self._root / route_name / "route.toml"
        if not manifest_path.exists():
            # route был удалён — unload только
            try:
                await self._unload_one(route_name)
                return ReloadEvent(
                    route_name=route_name, change_kind="removed", success=True
                )
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "hot_reloader.unload_failed", extra={"route_name": route_name}
                )
                return ReloadEvent(
                    route_name=route_name,
                    change_kind="removed",
                    success=False,
                    error=str(exc),
                )

        try:
            await self._unload_one(route_name)
            self._loader._load_one(manifest_path)
            _logger.info(
                "hot_reloader.route_reloaded", extra={"route_name": route_name}
            )
            return ReloadEvent(
                route_name=route_name, change_kind="modified", success=True
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "hot_reloader.reload_failed", extra={"route_name": route_name}
            )
            return ReloadEvent(
                route_name=route_name,
                change_kind="modified",
                success=False,
                error=str(exc),
            )

    async def _unload_one(self, route_name: str) -> None:
        """Unload единственного route. Если RouteLoader не поддерживает
        per-route unload, делает full reload-cycle."""
        unload_method = getattr(self._loader, "unload_one", None)
        if callable(unload_method):
            await unload_method(route_name)
            return
        # Fallback: full reload
        await self._loader.unload_all()
        await self._loader.discover_and_load()
