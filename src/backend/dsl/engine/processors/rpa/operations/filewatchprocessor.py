"""S171 M6 — FileWatchProcessor (gap fill).

File system watcher через ``watchdog``.
Async wrapper: запускает Observer в thread, ждёт timeout.
"""

from __future__ import annotations

import asyncio
import fnmatch
import threading
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


class _ChangeCollector:
    """Собирает file changes через watchdog Observer.

    Cycle 34 audit (DS3): pattern was declared but never applied —
    handler added every changed file regardless of configured glob.
    Filter now applied at add() time via :func:`fnmatch.fnmatch`.

    ADR-0368: пути дедуплицируются (create + modify одного файла — один
    элемент результата).
    """

    def __init__(self, pattern: str) -> None:
        self.changes: list[str] = []
        self._pattern = pattern
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def add(self, path: str) -> bool:
        """Добавить путь в результат (если он подходит под pattern и новый).

        Args:
            path: Путь из watchdog-события.

        Returns:
            ``True`` если путь добавлен (новый + подходит под pattern).

        """
        # Cycle 34: apply pattern filter to basename.
        import os

        basename = os.path.basename(path)
        if not fnmatch.fnmatch(basename, self._pattern):
            return False
        with self._lock:
            if path in self._seen:
                return False
            self._seen.add(path)
            self.changes.append(path)
        return True


class FileWatchProcessor(BaseProcessor):
    """Следит за изменениями в директории (create/modify/delete).

    Args:
        directory: Директория для наблюдения.
        pattern: Glob-фильтр (например ``"*.txt"``).
        timeout: Сколько секунд ждать (default 5.0).
        to: Куда записать список изменений (default ``"body.changes"``).

    """

    required_capability: ClassVar[str | None] = "rpa.file.watch"
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

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        if not await self.auth_check(exchange, action="read"):
            return
        # Второй независимый барьер безопасности: capability (``rpa.file.watch``)
        # ограничивает факт вызова, allowlist — путь наблюдения.
        from src.backend.dsl.engine.processors._path_safety import (
            PathTraversalError,
            validate_path,
        )

        try:
            safe_directory = validate_path(self.directory)
        except PathTraversalError as exc:
            exchange.fail(f"file_watch blocked: {exc}")
            return

        """Блокирует выполнение до появления файлов в директории (watchdog, синхронно)."""
        # ADR-0368: несуществующая директория → понятный failure вместо
        # необработанного FileNotFoundError из watchdog-потока.
        import os

        if not await asyncio.to_thread(os.path.isdir, safe_directory):
            exchange.fail(
                f"file_watch failed: directory does not exist: {safe_directory}"
            )
            return

        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as exc:
            raise RuntimeError("watchdog required: uv add watchdog") from exc

        collector = _ChangeCollector(self.pattern)
        loop = asyncio.get_running_loop()
        first_change = asyncio.Event()

        def _notify(path: str) -> None:
            """Событие watchdog-потока → collector + сигнал раннего выхода."""
            if collector.add(path):
                loop.call_soon_threadsafe(first_change.set)

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):  # type: ignore[override]
                if not event.is_directory:
                    _notify(str(event.src_path))

            def on_modified(self, event):  # type: ignore[override]
                if not event.is_directory:
                    _notify(str(event.src_path))

            def on_deleted(self, event):  # type: ignore[override]
                if not event.is_directory:
                    _notify(str(event.src_path))

        observer = Observer()
        try:
            observer.schedule(_Handler(), safe_directory, recursive=False)
            observer.start()
        except OSError as exc:
            exchange.fail(f"file_watch failed: observer start error: {exc}")
            return
        try:
            # ADR-0368: ранний выход по первому подходящему изменению
            # (иначе всегда ждём полный timeout).
            await asyncio.wait_for(first_change.wait(), timeout=self.timeout)
        except TimeoutError:
            pass
        finally:
            observer.stop()
            await asyncio.to_thread(observer.join, 2.0)

        _rpa_logger.info(
            "file_watch dir=%s pattern=%s changes=%d",
            safe_directory,
            self.pattern,
            len(collector.changes),
        )
        self.set_result(exchange, self.target, collector.changes)
