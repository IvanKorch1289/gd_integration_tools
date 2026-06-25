"""S171 M6 — FileWatchProcessor (gap fill).

File system watcher через ``watchdog``.
Async wrapper: запускает Observer в thread, ждёт timeout.
"""
from __future__ import annotations

import asyncio

import threading
import time
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


class _ChangeCollector:
    """Собирает file changes через watchdog Observer."""

    def __init__(self) -> None:
        self.changes: list[str] = []
        self._lock = threading.Lock()

    def add(self, path: str) -> None:
        with self._lock:
            self.changes.append(path)


class FileWatchProcessor(BaseProcessor):
    """Следит за изменениями в директории (create/modify/delete).

    Args:
        directory: Директория для наблюдения.
        pattern: Glob-фильтр (например ``"*.txt"``).
        timeout: Сколько секунд ждать (default 5.0).
        to: Куда записать список изменений (default ``"body.changes"``).
    """

    required_capability: str | None = "rpa.file.watch"
    audit_event: str | None = "rpa.file.watch"

    def __init__(
        self,
        *,
        directory: str,
        pattern: str = "*",
        timeout: float = 5.0,
        to: str = "body.changes",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "file_watch")
        self.directory = directory
        self.pattern = pattern
        self.timeout = timeout
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as exc:
            raise RuntimeError(
                "watchdog required: uv add watchdog"
            ) from exc

        collector = _ChangeCollector()

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):  # type: ignore[override]
                if not event.is_directory:
                    collector.add(str(event.src_path))

            def on_modified(self, event):  # type: ignore[override]
                if not event.is_directory:
                    collector.add(str(event.src_path))

            def on_deleted(self, event):  # type: ignore[override]
                if not event.is_directory:
                    collector.add(str(event.src_path))

        observer = Observer()
        observer.schedule(_Handler(), self.directory, recursive=False)
        observer.start()
        try:
            await asyncio.sleep(self.timeout)
        finally:
            observer.stop()
            observer.join(timeout=2.0)

        _rpa_logger.info(
            "file_watch dir=%s pattern=%s changes=%d",
            self.directory, self.pattern, len(collector.changes),
        )
        self.set_result(exchange, self.target, collector.changes)


import asyncio  # noqa: E402 (after class def)
