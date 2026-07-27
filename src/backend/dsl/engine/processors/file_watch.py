"""File Watch Processor — сканирование директории с фильтрацией по паттерну.

Sprint 36: добавляет возможность мониторинга директорий в DSL-маршрутах.
Использует ``watchdog`` для отслеживания изменений (lazy-import).

S178 #2 (lockjaw-vision-rocket.md): blocking ``os.walk`` /
``os.listdir`` обёрнуты в ``asyncio.to_thread`` чтобы не блокировать
event loop при сканировании больших директорий. ``os.path.isdir`` и
``os.stat`` тоже вынесены в thread pool.

S176 #4 (lockjaw-vision-rocket.md): добавлены опциональные параметры:
- ``patterns`` — tuple glob patterns (mutually exclusive с ``pattern``)
- ``directories`` — tuple директорий (mutually exclusive с ``directory``)
- ``max_results`` — лимит на количество файлов (None = unlimited)
Backward-compat: ``pattern`` и ``directory`` остаются обязательными
для simple use-case; новые параметры — additive extensions.
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

        # S176 #4: multiple patterns + directories + max_results
        builder.watch_files(
            patterns=("*.csv", "*.json", "*.parquet"),
            directories=("/data/incoming", "/data/archive"),
            max_results=500,
            include_subdirs=True,
        )

    Usage (YAML)::

        - file_watch:
            directory: "/data/incoming"
            pattern: "*.csv"
            result_property: "matched_files"

        # S176 #4 alternative: multi-pattern + multi-directory
        - file_watch:
            directories: ["/data/incoming", "/data/archive"]
            patterns: ["*.csv", "*.json"]
            max_results: 500
            include_subdirs: true

    Input:
        * ``exchange.get_property("watch_directory")`` — директория (override).
        * ``exchange.get_property("watch_patterns")`` — список patterns (override).
        * ``exchange.get_property("watch_max_results")`` — лимит (override).

    Output:
        * ``exchange.set_property(result_property, [{"path", "name", "size", "mtime"}])``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        directory: str | None = None,
        *,
        pattern: str | None = None,
        patterns: tuple[str, ...] | None = None,
        directories: tuple[str, ...] | None = None,
        max_results: int | None = None,
        result_property: str = "matched_files",
        include_subdirs: bool = False,
        name: str | None = None,
    ) -> None:
        """Инициализация FileWatchProcessor (S176 #4 — multi-pattern support).

        Args:
            directory: Single directory для сканирования. Mutually
                exclusive с ``directories``.
            pattern: Single glob pattern (e.g. ``"*.csv"``). Mutually
                exclusive с ``patterns``.
            patterns: Tuple из glob patterns. Если задан, переопределяет
                ``pattern``. Пример: ``("*.csv", "*.json")``.
            directories: Tuple из директорий для scan. Если задан,
                переопределяет ``directory``. Пример: ``("/data/in", "/data/out")``.
            max_results: Максимум файлов в результате (None = unlimited).
                Применяется ПОСЛЕ matching.
            result_property: Имя property в exchange для результата.
            include_subdirs: Рекурсивный обход (os.walk вместо os.listdir).
            name: Имя процессора.

        Raises:
            ValueError: Если не указаны ни directory, ни directories,
                или одновременно pattern и patterns.
        """
        # S176 #4: validation — нужен хотя бы один pattern и одна directory.
        if pattern is not None and patterns is not None:
            raise ValueError(
                "FileWatchProcessor: specify either `pattern` or `patterns`, not both"
            )
        if pattern is None and patterns is None:
            patterns = ("*",)  # default: match all files
        if directory is None and directories is None:
            raise ValueError(
                "FileWatchProcessor: specify either `directory` or `directories`"
            )
        if directory is not None and directories is not None:
            raise ValueError(
                "FileWatchProcessor: specify either `directory` or `directories`, not both"
            )

        effective_dirs = directories if directories is not None else (directory,)
        effective_patterns = patterns if patterns is not None else (pattern or "*",)

        # Name учитывает все директории для readability.
        dirs_label = ",".join(effective_dirs)
        super().__init__(name=name or f"file_watch:{dirs_label}")
        self._directory = directory
        self._directories = effective_dirs
        self._pattern = pattern
        self._patterns = effective_patterns
        self._result_property = result_property
        self._include_subdirs = include_subdirs
        self._max_results = max_results

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Сканирует директории и возвращает файлы по glob-patterns.

        S176 #4: поддерживает multi-directory + multi-pattern + max_results.
        S178 #2: blocking filesystem I/O (isdir/listdir/walk/stat) обёрнуты
        в ``asyncio.to_thread`` чтобы не блокировать event loop.

        Args:
            exchange: Текущий exchange; результат — в свойстве
                ``result_property`` (default: ``matched_files``).
            context: Контекст выполнения маршрута.
        """
        # S176 #4: support exchange-property overrides для dirs/patterns/max_results.
        prop_dir = exchange.get_property("watch_directory")
        prop_patterns = exchange.get_property("watch_patterns")
        prop_max_results = exchange.get_property("watch_max_results")

        effective_dirs = (prop_dir,) if prop_dir else self._directories
        effective_patterns_raw = (
            tuple(prop_patterns) if prop_patterns else self._patterns
        )
        # Single pattern (str) → wrap в tuple для единой обработки.
        effective_patterns = (
            (effective_patterns_raw,)
            if isinstance(effective_patterns_raw, str)
            else effective_patterns_raw
        )
        effective_max = (
            prop_max_results if prop_max_results is not None else self._max_results
        )

        # S176 #4: scan all directories, aggregate results.
        all_matched: list[dict[str, Any]] = []
        for directory in effective_dirs:
            # S178 #2: isdir() — blocking, переносим в thread.
            try:
                exists = await asyncio.to_thread(os.path.isdir, directory)
            except OSError as exc:
                exchange.fail(
                    f"file_watch: OS error checking {directory}: {exc}"
                )
                return

            if not exists:
                exchange.fail(
                    f"file_watch: directory does not exist: {directory}"
                )
                return

            # S178 #2: walk/listdir/stat — все blocking, делаем в thread pool.
            try:
                if self._include_subdirs:
                    raw_paths: list[tuple[str, os.stat_result]] = []
                    for pattern in effective_patterns:
                        raw_paths.extend(
                            await asyncio.to_thread(
                                _walk_matching_files, directory, pattern
                            )
                        )
                else:
                    raw_paths = []
                    for pattern in effective_patterns:
                        raw_paths.extend(
                            await asyncio.to_thread(
                                _list_matching_files, directory, pattern
                            )
                        )
            except OSError as exc:
                exchange.fail(
                    f"file_watch: OS error scanning {directory}: {exc}"
                )
                return

            for path, stat in raw_paths:
                all_matched.append(
                    {
                        "path": path,
                        "name": os.path.basename(path),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
                # S176 #4: short-circuit при достижении max_results.
                if (
                    effective_max is not None
                    and len(all_matched) >= effective_max
                ):
                    break
            if (
                effective_max is not None
                and len(all_matched) >= effective_max
            ):
                break

        exchange.set_property(self._result_property, all_matched)
        _logger.info(
            "file_watch: scanned dirs=%s patterns=%s matched=%d max_results=%s",
            list(effective_dirs),
            list(effective_patterns),
            len(all_matched),
            effective_max,
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        spec: dict[str, Any] = {
            "result_property": self._result_property,
        }
        # S176 #4: emit multi-form при наличии extensions.
        if len(self._directories) == 1 and self._pattern is not None:
            # Backward-compat: single dir + single pattern.
            spec["directory"] = self._directories[0]
            spec["pattern"] = self._pattern
        else:
            if len(self._directories) > 1:
                spec["directories"] = list(self._directories)
            else:
                spec["directory"] = self._directories[0]
            spec["patterns"] = list(self._patterns)
        if self._include_subdirs:
            spec["include_subdirs"] = True
        if self._max_results is not None:
            spec["max_results"] = self._max_results
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
