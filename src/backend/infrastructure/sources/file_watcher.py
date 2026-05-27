"""K7 W4 — :class:`FileWatcherSource` поверх ``watchfiles.awatch``.

Лёгкий async-generator wrapper для отслеживания изменений файловой системы.
Эмитит :class:`FileEvent` на каждое FS-событие (``added`` / ``modified`` /
``deleted``). Использует rust-based ``watchfiles`` (уже в deps).

Активируется через feature_flag ``eventbus_file_watcher`` (default-OFF).
"""

from __future__ import annotations

import asyncio

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

from watchfiles import Change

from src.backend.core.interfaces.source import EventCallback, SourceKind

if TYPE_CHECKING:
    from watchfiles import awatch as _awatch


@dataclass
class FileEvent:
    """Событие изменения файла на диске.

    Args:
        path: Абсолютный путь к изменённому файлу.
        change_type: Тип изменения: ``added``, ``modified`` или ``deleted``.
        timestamp: Unix-время момента обнаружения события (float, секунды).
    """

    path: Path
    change_type: Literal["added", "modified", "deleted"]
    timestamp: float = field(default_factory=time.time)


class FileWatcherSource:
    """Источник событий файловой системы на базе ``watchfiles.awatch``.

    Обёртка над rust-based async-генератором ``watchfiles.awatch``.
    Реализует протокол :class:`Source`.

    Args:
        source_id: Уникальный id (используется в SourceRegistry).
        path: Корневой путь для наблюдения.
        recursive: Рекурсивно обходить поддиректории (default ``True``).
        debounce: Debounce-окно в секундах (default ``0.1``). Преобразуется
            во внутренний формат milliseconds для ``watchfiles``.
        watch_filter: Опциональный фильтр ``(Change, str) -> bool``.
            ``None`` означает фильтр по умолчанию из ``watchfiles``.

    Example:
        .. code-block:: python

            async for event in FileWatcherSource("fw1", Path("/data")).stream():
                print(event.path, event.change_type)
    """

    kind: SourceKind = SourceKind.FILE_WATCHER

    def __init__(
        self,
        source_id: str,
        path: Path,
        *,
        recursive: bool = True,
        debounce: float = 0.1,
        watch_filter: Callable | None = None,
    ) -> None:
        self.source_id = source_id
        self._path = path
        self._recursive = recursive
        self._debounce_ms: int = max(1, int(debounce * 1000))
        self._watch_filter = watch_filter
        self._running = False
        self._on_event: EventCallback | None = None
        self._watch_task: asyncio.Task[None] | None = None

    async def start(self, on_event: EventCallback) -> None:
        """Начать отслеживание файлов."""
        if self._running:
            raise RuntimeError(f"FileWatcherSource(id={self.source_id!r}) уже запущен")
        self._running = True
        self._on_event = on_event
        from src.backend.core.utils.task_registry import get_task_registry

        self._watch_task = get_task_registry().create_task(
            self._run_watch(),
            name=f"file-watcher-{self.source_id}",
            deadline_seconds=None,
        )

    async def _run_watch(self) -> None:
        """Background task: run watch loop and emit events."""
        from datetime import UTC

        from src.backend.core.interfaces.source import SourceEvent

        try:
            async for event in self.stream():
                if self._on_event is not None:
                    source_event = SourceEvent(
                        source_id=self.source_id,
                        kind=self.kind,
                        payload={"path": str(event.path), "change_type": event.change_type},
                    )
                    await self._on_event(source_event)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Остановить отслеживание."""
        if not self._running:
            return
        self._running = False
        if self._watch_task is not None:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            self._watch_task = None

    async def health(self) -> bool:
        """Health check: always healthy if not crashed."""
        return self._running

    async def stream(self) -> AsyncIterator[FileEvent]:
        """Асинхронный генератор событий файловой системы.

        Yields:
            :class:`FileEvent` для каждого изменённого файла.

        Raises:
            asyncio.CancelledError: При отмене задачи (propagates наружу).
        """
        from watchfiles import awatch as _awatch  # noqa: PLC0415

        _change_map: dict[Change, Literal["added", "modified", "deleted"]] = {
            Change.added: "added",
            Change.modified: "modified",
            Change.deleted: "deleted",
        }

        kwargs: dict = {"recursive": self._recursive, "debounce": self._debounce_ms}
        if self._watch_filter is not None:
            kwargs["watch_filter"] = self._watch_filter

        try:
            async for changes in _awatch(self._path, **kwargs):
                for change, raw_path in changes:
                    change_type = _change_map.get(change, "modified")
                    yield FileEvent(path=Path(raw_path), change_type=change_type)
        except asyncio.CancelledError:
            raise
