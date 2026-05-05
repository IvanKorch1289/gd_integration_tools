"""Менеджер наблюдателей файловой системы (Wave B: ``watchfiles``-only).

Позволяет динамически создавать, удалять и перечислять
наблюдатели за директориями через REST API.
При появлении нового файла — передаёт его в DSL-маршрут.

Wave B: устранён polling-цикл ``os.scandir``; используется
``watchfiles.awatch`` (rust-based ``notify``). ``WatcherSpec.poll_interval``
сохранён в публичном API и используется как ``debounce`` для ``awatch``
(``poll_interval`` сек → ``debounce_ms = poll_interval * 1000``).
"""

import asyncio
import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from watchfiles import Change, awatch

from src.dsl.service import get_dsl_service

__all__ = ("WatcherManager", "WatcherSpec", "watcher_manager")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WatcherSpec:
    """Спецификация одного файлового наблюдателя.

    Attrs:
        id: Уникальный идентификатор наблюдателя.
        directory: Путь к наблюдаемой директории.
        pattern: Glob-паттерн файлов (например, ``*.csv``).
        route_id: DSL-маршрут для обработки файла.
        poll_interval: В Wave B — окно дебаунса (секунды), передаётся
            в ``watchfiles.awatch`` как ``debounce_ms``. Имя поля сохранено
            для обратной совместимости REST API.
        active: Флаг активности.
    """

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    directory: str = ""
    pattern: str = "*"
    route_id: str = ""
    poll_interval: float = 5.0
    active: bool = True


class WatcherManager:
    """Менеджер файловых наблюдателей.

    Управляет жизненным циклом наблюдателей:
    создание, запуск, остановка, удаление.
    Каждый наблюдатель работает как asyncio task поверх
    ``watchfiles.awatch``.
    """

    def __init__(self) -> None:
        self._watchers: dict[str, WatcherSpec] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_events: dict[str, asyncio.Event] = {}

    def add(self, spec: WatcherSpec) -> WatcherSpec:
        """Добавляет и запускает наблюдатель.

        Args:
            spec: Спецификация наблюдателя.

        Returns:
            Созданный ``WatcherSpec``.

        Raises:
            ValueError: Если директория не существует.
        """
        path = Path(spec.directory)
        if not path.is_dir():
            raise ValueError(f"Директория не найдена: {spec.directory}")

        self._watchers[spec.id] = spec
        stop_event = asyncio.Event()
        self._stop_events[spec.id] = stop_event
        self._tasks[spec.id] = asyncio.create_task(
            self._watch_loop(spec.id, stop_event)
        )

        logger.info(
            "Watcher %s запущен: dir=%s, pattern=%s, route=%s, debounce=%.1fs",
            spec.id,
            spec.directory,
            spec.pattern,
            spec.route_id,
            spec.poll_interval,
        )
        return spec

    def remove(self, watcher_id: str) -> None:
        """Удаляет наблюдатель.

        Args:
            watcher_id: ID наблюдателя.

        Raises:
            KeyError: Если наблюдатель не найден.
        """
        if watcher_id not in self._watchers:
            raise KeyError(f"Watcher {watcher_id} не найден")

        stop_event = self._stop_events.pop(watcher_id, None)
        if stop_event is not None:
            stop_event.set()

        task = self._tasks.pop(watcher_id, None)
        if task and not task.done():
            task.cancel()

        self._watchers.pop(watcher_id, None)

        logger.info("Watcher %s удалён", watcher_id)

    def list_watchers(self) -> list[dict[str, Any]]:
        """Возвращает список активных наблюдателей.

        Returns:
            Список словарей с параметрами наблюдателей.
        """
        return [
            {
                "id": spec.id,
                "directory": spec.directory,
                "pattern": spec.pattern,
                "route_id": spec.route_id,
                "poll_interval": spec.poll_interval,
                "active": spec.active,
            }
            for spec in self._watchers.values()
        ]

    async def _watch_loop(self, watcher_id: str, stop_event: asyncio.Event) -> None:
        """Цикл наблюдения за директорией поверх ``watchfiles.awatch``.

        При обнаружении нового или изменённого файла — отправляет его
        в DSL-маршрут. Дебаунс делегирован ``awatch`` (Wave B).
        """
        spec = self._watchers.get(watcher_id)
        if spec is None:
            return

        debounce_ms = max(int(spec.poll_interval * 1000), 0)
        try:
            async for changes in awatch(
                spec.directory,
                stop_event=stop_event,
                recursive=False,
                debounce=debounce_ms,
            ):
                spec = self._watchers.get(watcher_id)
                if spec is None or not spec.active:
                    return
                for change, raw_path in changes:
                    if change is Change.deleted:
                        continue
                    filename = Path(raw_path).name
                    if not fnmatch.fnmatch(filename, spec.pattern):
                        continue
                    await self._dispatch(spec, watcher_id, raw_path, filename)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Watcher %s: ошибка awatch-цикла", watcher_id)

    @staticmethod
    async def _dispatch(
        spec: WatcherSpec, watcher_id: str, filepath: str, filename: str
    ) -> None:
        """Отправляет одно файловое событие в DSL-маршрут."""
        logger.info("Watcher %s: новый файл %s", watcher_id, filepath)
        try:
            dsl = get_dsl_service()
            await dsl.dispatch(
                route_id=spec.route_id,
                body={
                    "filename": filename,
                    "filepath": filepath,
                    "watcher_id": watcher_id,
                },
                headers={"x-source": "filewatcher", "x-watcher-id": watcher_id},
            )
        except Exception:
            logger.exception("Watcher %s: ошибка обработки %s", watcher_id, filepath)

    async def stop_all(self) -> None:
        """Останавливает все наблюдатели."""
        for stop_event in self._stop_events.values():
            stop_event.set()
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self._stop_events.clear()
        self._watchers.clear()


watcher_manager = WatcherManager()
