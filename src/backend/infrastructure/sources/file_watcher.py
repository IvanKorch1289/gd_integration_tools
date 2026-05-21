"""K7 W4 — :class:`FileWatcherSource` поверх ``watchfiles.awatch``.

Лёгкий async-generator wrapper для отслеживания изменений файловой системы.
Эмитит :class:`FileEvent` на каждое FS-событие (``added`` / ``modified`` /
``deleted``). Использует rust-based ``watchfiles`` (уже в deps).

Активируется через feature_flag ``eventbus_file_watcher`` (default-OFF).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Callable, Literal

__all__ = ("FileWatcherSource", "FileEvent")


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
    Метод :meth:`stream` возвращает ``AsyncIterator[FileEvent]`` и корректно
    завершается при отмене (``asyncio.CancelledError`` пробрасывается наружу).

    Args:
        path: Корневой путь для наблюдения.
        recursive: Рекурсивно обходить поддиректории (default ``True``).
        debounce: Debounce-окно в секундах (default ``0.1``). Преобразуется
            во внутренний формат milliseconds для ``watchfiles``.
        watch_filter: Опциональный фильтр ``(Change, str) -> bool``.
            ``None`` означает фильтр по умолчанию из ``watchfiles``.

    Example:
        .. code-block:: python

            async for event in FileWatcherSource(Path("/data")).stream():
                print(event.path, event.change_type)
    """

    def __init__(
        self,
        path: Path,
        *,
        recursive: bool = True,
        debounce: float = 0.1,
        watch_filter: Callable | None = None,
    ) -> None:
        self._path = path
        self._recursive = recursive
        # watchfiles принимает debounce в миллисекундах (int)
        self._debounce_ms: int = max(1, int(debounce * 1000))
        self._watch_filter = watch_filter

    async def stream(self) -> AsyncIterator[FileEvent]:
        """Асинхронный генератор событий файловой системы.

        Yields:
            :class:`FileEvent` для каждого изменённого файла.

        Raises:
            asyncio.CancelledError: При отмене задачи (propagates наружу).
        """
        # Ленивый импорт тяжёлой зависимости
        from watchfiles import Change, awatch  # noqa: PLC0415

        _change_map: dict[Change, Literal["added", "modified", "deleted"]] = {
            Change.added: "added",
            Change.modified: "modified",
            Change.deleted: "deleted",
        }

        kwargs: dict = {"recursive": self._recursive, "debounce": self._debounce_ms}
        if self._watch_filter is not None:
            kwargs["watch_filter"] = self._watch_filter

        try:
            async for changes in awatch(self._path, **kwargs):
                for change, raw_path in changes:
                    change_type = _change_map.get(change, "modified")
                    yield FileEvent(path=Path(raw_path), change_type=change_type)
        except asyncio.CancelledError:
            raise
