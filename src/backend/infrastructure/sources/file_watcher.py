"""K7 W4 — :class:`FileWatcherSource` поверх ``watchfiles.awatch``.

Лёгкий async-generator wrapper для отслеживания изменений файловой системы.
Эмитит :class:`FileEvent` на каждое FS-событие (``added`` / ``modified`` /
``deleted``). Использует rust-based ``watchfiles`` (уже в deps).

Активируется через feature_flag ``eventbus_file_watcher`` (default-OFF).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from watchfiles import Change

from src.backend.core.interfaces.source import EventCallback, SourceKind

if TYPE_CHECKING:
    pass


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
        path: Корневой путь (или несколько через ``paths``) для наблюдения.
        paths: Список путей для наблюдения. Объединяется с ``path``.
        recursive: Рекурсивно обходить поддиректории (default ``True``).
        debounce: Debounce-окно в секундах (default ``0.1``). Преобразуется
            во внутренний формат milliseconds для ``watchfiles``.
        watch_filter: Опциональный фильтр ``(Change, str) -> bool``.
            ``None`` означает фильтр по умолчанию из ``watchfiles``.
        glob_include: Glob-паттерн(ы), которым должен соответствовать путь.
            Поддерживается ``**`` (Python 3.14 ``Path.match``).
        glob_exclude: Glob-паттерн(ы), исключающие путь из событий.
        batch_size: Максимальное число событий в одном батче.
        batch_window: Максимальное окно (сек) накопления батча.

    Example:
        .. code-block:: python

            async for event in FileWatcherSource("fw1", Path("/data")).stream():
                print(event.path, event.change_type)
    """

    kind: SourceKind = SourceKind.FILE_WATCHER

    def __init__(
        self,
        source_id: str,
        path: Path | str | None = None,
        *,
        paths: Sequence[Path | str] | None = None,
        recursive: bool = True,
        debounce: float = 0.1,
        watch_filter: Callable | None = None,
        glob_include: list[str] | str | None = None,
        glob_exclude: list[str] | str | None = None,
        batch_size: int | None = None,
        batch_window: float | None = None,
    ) -> None:
        self.source_id = source_id
        self._paths = self._normalize_paths(path, paths)
        self._recursive = recursive
        self._debounce_ms: int = max(1, int(debounce * 1000))
        self._watch_filter = watch_filter
        self._glob_include = self._normalize_glob(glob_include)
        self._glob_exclude = self._normalize_glob(glob_exclude)
        self._batch_size = batch_size
        self._batch_window = batch_window
        self._running = False
        self._on_event: EventCallback | None = None
        self._watch_task: asyncio.Task[None] | None = None

    @staticmethod
    def _normalize_paths(
        path: Path | str | None, paths: Sequence[Path | str] | None
    ) -> list[Path]:
        """Приводит ``path``/``paths`` к списку абсолютных ``Path``."""
        raw: list[Path | str] = []
        if path is not None:
            raw.append(path)
        if paths is not None:
            if isinstance(paths, (str, Path)):
                raw.append(paths)
            else:
                raw.extend(paths)
        if not raw:
            raise ValueError("FileWatcherSource requires at least one path")
        return [Path(p).resolve() for p in raw]

    @staticmethod
    def _normalize_glob(value: list[str] | str | None) -> list[str]:
        """Приводит glob-аргумент к списку строк."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return list(value)

    def _matches_glob(self, file_path: Path) -> bool:
        """Проверяет путь по include/exclude glob-паттернам."""
        if self._glob_include and not any(
            file_path.match(p) for p in self._glob_include
        ):
            return False
        if self._glob_exclude and any(file_path.match(p) for p in self._glob_exclude):
            return False
        return True

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

        from src.backend.core.interfaces.source import SourceEvent

        try:
            if self._batch_size or self._batch_window:
                async for batch in self._stream_batches():
                    if self._on_event is not None:
                        await self._on_event(
                            SourceEvent(
                                source_id=self.source_id,
                                kind=self.kind,
                                payload={
                                    "events": [
                                        {
                                            "path": str(event.path),
                                            "change_type": event.change_type,
                                        }
                                        for event in batch
                                    ],
                                    "count": len(batch),
                                },
                            )
                        )
            else:
                async for event in self.stream():
                    if self._on_event is not None:
                        await self._on_event(
                            SourceEvent(
                                source_id=self.source_id,
                                kind=self.kind,
                                payload={
                                    "path": str(event.path),
                                    "change_type": event.change_type,
                                },
                            )
                        )
        except asyncio.CancelledError:
            pass

    async def _stream_batches(self) -> AsyncIterator[list[FileEvent]]:
        """Группирует события из ``stream()`` по размеру и/или окну.

        Первое событие в батче ждётся сколь угодно долго (нет таймаута
        на пустом батче). После появления первого события активируется
        ``batch_window`` и/или проверяется ``batch_size``.

        Реализовано через ``asyncio.Queue`` + отдельную producer-task,
        чтобы ``wait_for`` не отменял async-generator ``stream()``.
        """
        queue: asyncio.Queue[FileEvent | None] = asyncio.Queue()
        producer = asyncio.create_task(self._fill_queue(queue))
        try:
            batch: list[FileEvent] = []
            while True:
                if batch and self._batch_window is not None:
                    try:
                        event = await asyncio.wait_for(
                            queue.get(), timeout=self._batch_window
                        )
                    except TimeoutError:
                        yield batch
                        batch = []
                        continue
                else:
                    event = await queue.get()

                if event is None:
                    if batch:
                        yield batch
                    return

                batch.append(event)
                if self._batch_size and len(batch) >= self._batch_size:
                    yield batch
                    batch = []
        finally:
            producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass

    async def _fill_queue(self, queue: asyncio.Queue[FileEvent | None]) -> None:
        """Читает ``stream()`` и складывает события в очередь.

        Sentinel ``None`` сигнализирует об окончании потока.
        """
        try:
            async for event in self.stream():
                queue.put_nowait(event)
        finally:
            queue.put_nowait(None)

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
        from watchfiles import awatch as _awatch

        _change_map: dict[Change, Literal["added", "modified", "deleted"]] = {
            Change.added: "added",
            Change.modified: "modified",
            Change.deleted: "deleted",
        }

        kwargs: dict = {"recursive": self._recursive, "debounce": self._debounce_ms}
        if self._watch_filter is not None:
            kwargs["watch_filter"] = self._watch_filter

        try:
            async for changes in _awatch(*self._paths, **kwargs):
                for change, raw_path in changes:
                    file_path = Path(raw_path)
                    if not self._matches_glob(file_path):
                        continue
                    change_type = _change_map.get(change, "modified")
                    yield FileEvent(path=file_path, change_type=change_type)
        except asyncio.CancelledError:
            raise
