"""File Watch Processor — сканирование директории с фильтрацией по паттерну.

Sprint 36: добавляет возможность мониторинга директорий в DSL-маршрутах.
Использует ``watchdog`` для отслеживания изменений (lazy-import).
"""

from __future__ import annotations

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

        Директория берётся из ``self._directory`` или свойства
        ``watch_directory``. При ``include_subdirs`` — рекурсивный обход
        через ``os.walk``. Результат — список dict с path, name, size, mtime.

        Args:
            exchange: Текущий exchange; результат — в свойстве
                ``result_property`` (default: ``matched_files``).
            context: Контекст выполнения маршрута.
        """
        directory = exchange.get_property("watch_directory") or self._directory

        if not os.path.isdir(directory):
            exchange.fail(f"file_watch: directory does not exist: {directory}")
            return

        matched: list[dict[str, Any]] = []
        try:
            if self._include_subdirs:
                for root, _dirs, files in os.walk(directory):
                    for filename in files:
                        if fnmatch.fnmatch(filename, self._pattern):
                            path = os.path.join(root, filename)
                            stat = os.stat(path)
                            matched.append(
                                {
                                    "path": path,
                                    "name": filename,
                                    "size": stat.st_size,
                                    "mtime": stat.st_mtime,
                                }
                            )
            else:
                for filename in os.listdir(directory):
                    if fnmatch.fnmatch(filename, self._pattern):
                        path = os.path.join(directory, filename)
                        if os.path.isfile(path):
                            stat = os.stat(path)
                            matched.append(
                                {
                                    "path": path,
                                    "name": filename,
                                    "size": stat.st_size,
                                    "mtime": stat.st_mtime,
                                }
                            )
        except OSError as exc:
            exchange.fail(f"file_watch: OS error scanning {directory}: {exc}")
            return

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
