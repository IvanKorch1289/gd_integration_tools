"""Горячая перезагрузка конфигурации без рестарта приложения.

Модуль использует :mod:`watchfiles` для отслеживания изменений в ``.env``
и YAML-конфигах, и публикует событие через callback-реестр. Подписчики
(LLM-провайдеры, cache, feature flags) переподгружают свои настройки.

Также доступен ручной триггер через админ-эндпоинт ``POST /admin/config/reload``
для ситуаций, когда файловая система не проксируется в контейнер (read-only FS).

Принципы:

* Watcher живёт в отдельной asyncio-таске, запускается в ``lifespan.startup``.
* Callbacks выполняются последовательно, чтобы избежать гонок.
* Ошибки callback'а логируются, но не останавливают watcher.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

__all__ = ("ConfigHotReloader", "get_hot_reloader")

logger = logging.getLogger("config.hot_reload")

ReloadCallback = Callable[[], Awaitable[None] | None]


class ConfigHotReloader:
    """Отслеживает изменения конфигурационных файлов и вызывает callback'и.

    Использование::

        reloader = get_hot_reloader()
        reloader.watch(Path(".env"))
        reloader.watch(Path("configs/routes.yaml"))
        reloader.on_reload(lambda: settings.reload())
        await reloader.start()

    После изменения любого отслеживаемого файла все зарегистрированные
    callback'и будут вызваны (по порядку регистрации).
    """

    def __init__(self, *, debounce_ms: int = 500) -> None:
        self._paths: set[Path] = set()
        self._callbacks: list[ReloadCallback] = []
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._debounce_ms = debounce_ms

    def watch(self, path: str | Path) -> None:
        """Добавляет файл или директорию в список отслеживаемых."""
        self._paths.add(Path(path))

    def on_reload(self, callback: ReloadCallback) -> None:
        """Регистрирует callback, вызываемый при изменении."""
        self._callbacks.append(callback)

    async def trigger_reload(self, reason: str = "manual") -> dict[str, Any]:
        """Вручную вызывает все callback'и (для админ-эндпоинта).

        Возвращает отчёт с количеством успешных/провалившихся callback'ов.
        """
        ok, failed = 0, []
        for cb in self._callbacks:
            try:
                result = cb()
                if asyncio.iscoroutine(result):
                    await result
                ok += 1
            except Exception as exc:  # noqa: BLE001
                failed.append(
                    {"callback": getattr(cb, "__name__", repr(cb)), "error": str(exc)}
                )
                logger.error("Hot-reload callback failed: %s", exc)
        logger.info("Config reloaded (%s): %d OK, %d failed", reason, ok, len(failed))
        return {"reason": reason, "succeeded": ok, "failed": failed}

    async def start(self) -> None:
        """Запускает watcher в отдельной таске."""
        if self._task and not self._task.done():
            return  # уже запущен
        self._stop_event.clear()
        self._task = asyncio.create_task(self._watch_loop(), name="config-hot-reload")
        logger.info("Config hot-reload started, watching %d paths", len(self._paths))

    async def stop(self) -> None:
        """Останавливает watcher."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self) -> None:
        """Главный цикл: слушает watchfiles, дебаунсит, вызывает callback'и."""
        try:
            from watchfiles import awatch
        except ImportError:
            logger.warning("watchfiles не установлен — hot-reload отключён")
            return

        paths = [str(p) for p in self._paths if p.exists()]
        if not paths:
            logger.warning("Hot-reload: нет существующих путей для наблюдения")
            return

        # step=debounce_ms собирает пакет изменений за интервал — избегает
        # множественных срабатываний при сохранении редактором (который
        # обычно создаёт tmp-файл и затем переименовывает).
        async for _changes in awatch(
            *paths, step=self._debounce_ms, stop_event=self._stop_event
        ):
            await self.trigger_reload(reason="file-change")


_reloader: ConfigHotReloader | None = None


def get_hot_reloader() -> ConfigHotReloader:
    """Singleton hot-reloader'а для всего приложения."""
    global _reloader
    if _reloader is None:
        _reloader = ConfigHotReloader()
    return _reloader
