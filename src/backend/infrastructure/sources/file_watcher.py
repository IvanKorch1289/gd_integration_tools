"""W23.3 — :class:`FileWatcherSource` поверх ``watchfiles``.

Лёгкий wrapper, эмитит ``SourceEvent`` на каждое FS-событие
(``added`` / ``modified`` / ``deleted``) для файлов, удовлетворяющих
glob-паттерну. Использует rust-based ``watchfiles`` (уже в deps).
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from watchfiles import Change, awatch

from src.backend.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.backend.infrastructure.sources._lifecycle import graceful_cancel

if TYPE_CHECKING:
    pass

__all__ = ("FileWatcherSource",)

logger = logging.getLogger("infrastructure.sources.file_watcher")


_CHANGE_TO_NAME = {
    Change.added: "added",
    Change.modified: "modified",
    Change.deleted: "deleted",
}


class FileWatcherSource:
    """Source, эмитящий событие на каждое изменение файла.

    Args:
        source_id: Уникальный id.
        directory: Корневая директория (рекурсивно).
        pattern: Glob-паттерн (default ``*``).
        recursive: Рекурсивно ли обходить (default ``True``).
        debounce_ms: Debounce окно для watchfiles (default 200ms).
    """

    kind: SourceKind = SourceKind.FILE_WATCHER

    def __init__(
        self,
        source_id: str,
        *,
        directory: str,
        pattern: str = "*",
        recursive: bool = True,
        debounce_ms: int = 200,
    ) -> None:
        self.source_id = source_id
        self._dir = Path(directory)
        self._pattern = pattern
        self._recursive = recursive
        self._debounce = debounce_ms
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self, on_event: EventCallback) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError(f"FileWatcherSource(id={self.source_id!r}) уже запущен")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(on_event))
        logger.info(
            "FileWatcherSource started: id=%s dir=%s pattern=%s",
            self.source_id,
            self._dir,
            self._pattern,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        await graceful_cancel(self._task, source_id=self.source_id)
        self._task = None
        logger.info("FileWatcherSource stopped: id=%s", self.source_id)

    async def health(self) -> bool:
        return self._task is not None and not self._task.done()

    def _match(self, path: str) -> bool:
        return fnmatch.fnmatch(Path(path).name, self._pattern)

    async def _run(self, on_event: EventCallback) -> None:
        async for changes in awatch(
            self._dir,
            stop_event=self._stop_event,
            recursive=self._recursive,
            debounce=self._debounce,
        ):
            for change, path in changes:
                if not self._match(path):
                    continue
                event = SourceEvent(
                    source_id=self.source_id,
                    kind=self.kind,
                    payload={"path": path, "change": _CHANGE_TO_NAME.get(change, "?")},
                    event_time=datetime.now(UTC),
                    metadata={"directory": str(self._dir), "pattern": self._pattern},
                )
                try:
                    await on_event(event)
                except Exception as exc:
                    logger.error(
                        "FileWatcherSource on_event failed (%s): %s", path, exc
                    )
