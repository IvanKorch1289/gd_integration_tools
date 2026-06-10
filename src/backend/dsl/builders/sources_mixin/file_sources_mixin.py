from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

class FileSourcesMixin:
    """file-based source registration (filewatcher) для RouteBuilder. S57 W2 extraction."""

    __slots__ = ()

    @classmethod
    def from_filewatcher(
        cls, route_id: str, path: str, *, recursive: bool = True, **kwargs: Any
    ) -> RouteBuilder:
        """Создаёт маршрут с источником FileWatcher (watchfiles.awatch).

        Лениво импортирует :class:`FileWatcherSource` из
        ``infrastructure.sources.file_watcher``.
        Активируется через feature_flag ``eventbus_file_watcher`` (default-OFF).

        Args:
            route_id: Уникальный ID маршрута.
            path: Корневой путь для наблюдения (строка или Path).
            recursive: Рекурсивно обходить поддиректории (default ``True``).
            **kwargs: Дополнительные параметры для :class:`FileWatcherSource`
                (debounce, watch_filter).

        Returns:
            RouteBuilder с ``source`` установленным в ``filewatcher:<path>``.

        Example::

            route = (
                RouteBuilder.from_filewatcher(
                    "config.hotreload",
                    path="/etc/app/config",
                    recursive=False,
                )
                .dispatch_action("config.reload")
                .build()
            )
        """
        import importlib
        from pathlib import Path

        mod = importlib.import_module("src.backend.infrastructure.sources.file_watcher")
        FileWatcherSource = mod.FileWatcherSource
        source_instance = FileWatcherSource(
            path=Path(path), recursive=recursive, **kwargs
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"filewatcher:{path}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

