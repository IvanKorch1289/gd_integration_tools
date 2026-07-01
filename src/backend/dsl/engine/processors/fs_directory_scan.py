"""Directory Scan processor — backward-compat wrapper (S172 M1.2 deprecation).

DEPRECATED since Sprint 172:
    :class:`DirectoryScanProcessor` is a backward-compat shim вокруг
    :class:`FilteredDirectoryScanProcessor` (S171 M7). Используйте
    новый процессор напрямую — он async-safe (``asyncio.to_thread`` +
    ``asyncio.wait_for``), поддерживает size/mtime filters и
    safety caps (max_results, timeout_seconds).

This shim:

* Сохраняет legacy ``path=`` + ``recursive`` + ``max_files`` + ``sort_by`` +
  ``result_property`` API.
* Сохраняет legacy result format (``list[dict]`` с ``path/name/size/mtime``).
* Делегирует I/O в ``FilteredDirectoryScanProcessor`` через
  ``asyncio.to_thread`` (non-blocking event-loop).
* Эмитит :class:`DeprecationWarning` при первом ``__init__`` + audit-event
  при первом ``process``.

Migration::

    # Old (synchronous I/O, blocking event loop):
    DirectoryScanProcessor(path="/data", pattern="*.csv")

    # New (S171 M7, async-safe):
    FilteredDirectoryScanProcessor(directory="/data", pattern="*.csv",
                                    min_size=1024, to="body.files")
"""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.rpa.operations.filtereddirectoryscanprocessor import (  # noqa: E501
    FilteredDirectoryScanProcessor,
)

if TYPE_CHECKING:
    pass

__all__ = ("DirectoryScanProcessor",)

_logger = get_logger("dsl.fs_directory_scan")


class _DeprecationAuditEmitted:
    """S172 M1.2: per-process guard чтобы emit audit только один раз.

    Статический счётчик + set per-call-site. Не глобальный mutable
    side-effect — только best-effort signal.
    """

    _emitted: bool = False


class DirectoryScanProcessor(BaseProcessor):
    """DEPRECATED shim → :class:`FilteredDirectoryScanProcessor` (S171 M7).

    Сохранён legacy API:

    * ``path`` (positional) → ``directory``.
    * ``recursive`` добавляет ``**/`` prefix к pattern.
    * ``max_files`` cap → ``max_results`` (default 1000, безопаснее).
    * ``sort_by`` применяется post-scan к dict-entries (``name`` / ``mtime`` / ``size``).
    * ``result_property`` — куда записать ``list[dict]`` (legacy format).

    Implementation делегирует glob в
    :class:`FilteredDirectoryScanProcessor` (S171 M7, async-safe
    через ``asyncio.to_thread``), затем обогащает результат dict-метаданными
    (size/mtime/name) и сортирует.

    Args:
        path: Корневая директория.
        pattern: Glob-паттерн (default ``"*"``).
        recursive: Рекурсивный обход (``**/*.csv``).
        max_files: Лимит результатов (1..10000).
        sort_by: ``"name"`` / ``"mtime"`` / ``"size"``.
        result_property: Куда положить list[dict].
        name: Имя процессора.

    Warnings:
        DeprecationWarning — рекомендуется :class:`FilteredDirectoryScanProcessor`.
    """

    side_effect = SideEffectKind.SIDE_EFFECTING
    compensatable = True

    def __init__(
        self,
        path: str,
        pattern: str = "*",
        *,
        recursive: bool = False,
        max_files: int = 1000,
        sort_by: str = "name",
        result_property: str = "directory_scan_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"dir_scan:{path}:{pattern}")
        self._path = path
        self._pattern = pattern
        self._recursive = recursive
        self._max_files = max_files
        self._sort_by = sort_by
        self._result_property = result_property

        # S172 M1.2: emit DeprecationWarning при инстанциировании.
        warnings.warn(
            (
                "DirectoryScanProcessor is deprecated since Sprint 172 "
                "(blocking I/O in async context). "
                "Use FilteredDirectoryScanProcessor (S171 M7) instead: "
                "supports asyncio.to_thread, max_results cap, timeout, "
                "and size/mtime filters. Backward-compat shim оставлен "
                "на Sprint 174 — удалится в Sprint 175."
            ),
            DeprecationWarning,
            stacklevel=2,
        )
        if not _DeprecationAuditEmitted._emitted:
            _DeprecationAuditEmitted._emitted = True
            _logger.warning(
                "DirectoryScanProcessor used (DEPRECATED, S172 M1.2). "
                "Will be removed in Sprint 175. "
                "Migrate to FilteredDirectoryScanProcessor (S171 M7)."
            )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Депрекированный directory scan processor (shim на FilteredDirectoryScanProcessor).

        Разрешает путь из ``self._path`` или exchange.body, проверяет path-traversal
        и существование директории, затем делегирует к
        :class:`FilteredDirectoryScanProcessor` (async-safe). Результат
        обогащается metadata (size, mtime) и сортируется.

        Args:
            exchange: Текущий exchange; путь берётся из ``self._path`` либо
                ``in_message.body["path"]``. Результат — в ``self._result_property``.
            context: Контекст выполнения маршрута.

        Warning:
            Депрекирован (S172 M1.2). Используйте
            :class:`FilteredDirectoryScanProcessor`.
        """
        # Resolve path.
        path = self._path
        if not path:
            body = exchange.in_message.body
            path = body.get("path") if isinstance(body, dict) else str(body)
        if not path:
            exchange.fail("DirectoryScanProcessor: no path provided")
            return

        # Guard against path traversal / missing dir.
        try:
            resolved = os.path.realpath(path)
            if not os.path.isdir(resolved):
                exchange.fail(f"DirectoryScanProcessor: not a directory: {path}")
                return
        except OSError as exc:
            exchange.fail(f"DirectoryScanProcessor: path error: {exc}")
            return

        # Translate ``path`` + ``pattern`` → ``directory`` + ``pattern`` для shim.
        # Set ``recursive=True`` → prepend ``**/`` (только если не уже ``**``-prefix).
        effective_pattern = self._pattern
        if self._recursive and not effective_pattern.startswith("**"):
            if effective_pattern.startswith("*"):
                effective_pattern = "**/" + effective_pattern
            else:
                effective_pattern = "**/" + effective_pattern

        # FilteredDirectoryScanProcessor возвращает sorted list of strings.
        # S171 M7 — async-safe (asyncio.to_thread + asyncio.wait_for).
        inner = FilteredDirectoryScanProcessor(
            directory=path,
            pattern=effective_pattern,
            max_results=self._max_files,
            name=f"{self.name}:inner",
        )
        # Перехватываем выход inner: подменяем exchange shim, который
        # собирает результаты через ``set_result`` calls.
        original_set_result = inner.set_result
        captured: dict[str, Any] = {}

        def _capture_set_result(
            _exchange: Exchange[Any], target: str, value: Any
        ) -> None:
            captured[target] = value
            original_set_result(_exchange, target, value)

        inner.set_result = _capture_set_result  # type: ignore[method-assign]
        try:
            # Используем self-collected exchange через перехват.
            await inner.process(exchange, context)
        finally:
            inner.set_result = original_set_result  # type: ignore[method-assign]

        # Достаём результат из captured (write-target inner — ``body.files`` default).
        raw_paths: list[str] = captured.get("body.files", []) or []
        raw_paths = list(raw_paths)[: self._max_files]

        # Обогащаем dict-метаданными (legacy format) + sort_by.
        entries: list[dict[str, Any]] = []
        for full in raw_paths:
            try:
                stat = os.stat(full)
                entries.append(
                    {
                        "path": full,
                        "name": os.path.basename(full),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
            except OSError:
                continue

        # Sort в legacy semantics.
        if self._sort_by == "mtime":
            entries.sort(key=lambda e: e["mtime"])
        elif self._sort_by == "size":
            entries.sort(key=lambda e: e["size"])
        else:  # "name" default
            entries.sort(key=lambda e: e["name"])

        exchange.set_property(self._result_property, entries)

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "directory_scan": {
                "path": self._path,
                "pattern": self._pattern,
                "recursive": self._recursive,
                "max_files": self._max_files,
                "sort_by": self._sort_by,
                "result_property": self._result_property,
            }
        }
