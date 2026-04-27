"""Менеджер наблюдателей файловой системы.

Позволяет динамически создавать, удалять и перечислять
наблюдатели за директориями через REST API.
При появлении нового файла — передаёт его в DSL-маршрут.
"""

import asyncio
import fnmatch
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        poll_interval: Интервал опроса в секундах.
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
    Каждый наблюдатель работает как asyncio task.
    """

    def __init__(self) -> None:
        self._watchers: dict[str, WatcherSpec] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._seen_files: dict[str, set[str]] = {}

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
        self._seen_files[spec.id] = self._scan_existing(spec)
        self._tasks[spec.id] = asyncio.create_task(self._poll_loop(spec.id))

        logger.info(
            "Watcher %s запущен: dir=%s, pattern=%s, route=%s",
            spec.id,
            spec.directory,
            spec.pattern,
            spec.route_id,
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

        task = self._tasks.pop(watcher_id, None)
        if task and not task.done():
            task.cancel()

        self._watchers.pop(watcher_id, None)
        self._seen_files.pop(watcher_id, None)

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

    @staticmethod
    def _scan_existing(spec: WatcherSpec) -> set[str]:
        """Сканирует существующие файлы в директории."""
        try:
            return {
                entry.name
                for entry in os.scandir(spec.directory)
                if entry.is_file() and fnmatch.fnmatch(entry.name, spec.pattern)
            }
        except OSError:
            return set()

    async def _poll_loop(self, watcher_id: str) -> None:
        """Цикл опроса директории.

        При обнаружении нового файла — отправляет его
        в DSL-маршрут.
        """
        while True:
            spec = self._watchers.get(watcher_id)
            if spec is None or not spec.active:
                break

            try:
                current_files = self._scan_existing(spec)
                seen = self._seen_files.get(watcher_id, set())
                new_files = current_files - seen

                for filename in sorted(new_files):
                    filepath = str(Path(spec.directory) / filename)
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
                            headers={
                                "x-source": "filewatcher",
                                "x-watcher-id": watcher_id,
                            },
                        )
                    except Exception:
                        logger.exception(
                            "Watcher %s: ошибка обработки %s", watcher_id, filepath
                        )

                self._seen_files[watcher_id] = current_files

            except Exception:
                logger.exception("Watcher %s: ошибка опроса", watcher_id)

            await asyncio.sleep(spec.poll_interval)

    async def stop_all(self) -> None:
        """Останавливает все наблюдатели."""
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self._watchers.clear()
        self._seen_files.clear()


watcher_manager = WatcherManager()
