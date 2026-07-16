"""File Watch Processor — сканирование директории с фильтрацией по паттерну.

Sprint 36: добавляет возможность мониторинга директорий в DSL-маршрутах.
Использует ``watchdog`` для отслеживания изменений (lazy-import).

S178 #2 (lockjaw-vision-rocket.md): blocking ``os.walk`` /
``os.listdir`` обёрнуты в ``asyncio.to_thread`` чтобы не блокировать
event loop при сканировании больших директорий. ``os.path.isdir`` и
``os.stat`` тоже вынесены в thread pool.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry.processor import processor

__all__ = ("FileWatchProcessor",)

_logger = get_logger("dsl.file_watch")


@processor(
    "file_watch", namespace="core", capabilities=("fs.watch",), tags=["fs", "watch"]
)
class FileWatchProcessor(BaseProcessor):
    """Сканирует директорию и помещает найденные файлы в exchange property.

    Usage (Python builder)::

        builder.watch_files("/data/incoming", pattern="*.csv")

    Usage (YAML)::

        - file_watch:
            directory: "/data/incoming"
            pattern: "*.csv"
            result_property: "matched_files"

    Input:
        * ``exchange.get_property("watch_directory")`` — директория (override).

    Output:
        * ``exchange.set_property(result_property, [{"path", "name", "size", "mtime"}])``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        directory: str,
        *,
        pattern: str = "*",
        result_property: str = "matched_files",
        include_subdirs: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"file_watch:{directory}")
        self._directory = directory
        self._pattern = pattern
        self._result_property = result_property
        self._include_subdirs = include_subdirs

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Сканирует директорию и возвращает файлы по glob-pattern.

        S178 #2: blocking filesystem I/O (isdir/listdir/walk/stat) обёрнуты
        в ``asyncio.to_thread`` чтобы не блокировать event loop.
        Pattern matching остаётся в event loop (cheap CPU).

        Args:
            exchange: Текущий exchange; результат — в свойстве
                ``result_property`` (default: ``matched_files``).
            context: Контекст выполнения маршрута.
        """
        directory = exchange.get_property("watch_directory") or self._directory

        # S178 #2: isdir() — blocking, переносим в thread.
        try:
            exists = await asyncio.to_thread(os.path.isdir, directory)
        except OSError as exc:
            exchange.fail(f"file_watch: OS error checking {directory}: {exc}")
            return

        if not exists:
            exchange.fail(f"file_watch: directory does not exist: {directory}")
            return

        # S178 #2: walk/listdir/stat — все blocking, делаем в thread pool.
        try:
            if self._include_subdirs:
                raw_paths = await asyncio.to_thread(
                    _walk_matching_files, directory, self._pattern
                )
            else:
                raw_paths = await asyncio.to_thread(
                    _list_matching_files, directory, self._pattern
                )
        except OSError as exc:
            exchange.fail(f"file_watch: OS error scanning {directory}: {exc}")
            return

        matched: list[dict[str, Any]] = [
            {
                "path": path,
                "name": os.path.basename(path),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
            for path, stat in raw_paths
        ]

        exchange.set_property(self._result_property, matched)
        _logger.info(
            "file_watch: scanned %s, pattern=%s, matched=%d",
            directory,
            self._pattern,
            len(matched),
        )

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {
            "directory": self._directory,
            "pattern": self._pattern,
            "result_property": self._result_property,
        }
        if self._include_subdirs:
            spec["include_subdirs"] = True
        return {"file_watch": spec}


def _list_matching_files(
    directory: str, pattern: str
) -> list[tuple[str, os.stat_result]]:
    """Sync helper: list files в directory matching glob pattern.

    Returns:
        List of (full_path, stat_result) tuples. Blocking I/O — вызывать
        через ``asyncio.to_thread``.
    """
    matched: list[tuple[str, os.stat_result]] = []
    for filename in os.listdir(directory):
        if fnmatch.fnmatch(filename, pattern):
            path = os.path.join(directory, filename)
            if os.path.isfile(path):
                matched.append((path, os.stat(path)))
    return matched


def _walk_matching_files(
    directory: str, pattern: str
) -> list[tuple[str, os.stat_result]]:
    """Sync helper: recursive walk + glob filter.

    Returns:
        List of (full_path, stat_result) tuples. Blocking I/O — вызывать
        через ``asyncio.to_thread``.
    """
    matched: list[tuple[str, os.stat_result]] = []
    for root, _dirs, files in os.walk(directory):
        for filename in files:
            if fnmatch.fnmatch(filename, pattern):
                path = os.path.join(root, filename)
                matched.append((path, os.stat(path)))
    return matched
