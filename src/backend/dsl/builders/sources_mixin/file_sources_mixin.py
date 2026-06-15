from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class FileSourcesMixin:
    """file-based source registration (filewatcher) для RouteBuilder. S57 W2 extraction."""

    __slots__ = ()

    @classmethod
    def from_filewatcher(
        cls,
        route_id: str,
        path: str | Path | None = None,
        *,
        paths: str | Path | list[str | Path] | None = None,
        recursive: bool = True,
        glob_include: list[str] | str | None = None,
        glob_exclude: list[str] | str | None = None,
        batch_size: int | None = None,
        batch_window: float | None = None,
        **kwargs: Any,
    ) -> RouteBuilder:
        """Создаёт маршрут с источником FileWatcher (watchfiles.awatch).

        Лениво импортирует :class:`FileWatcherSource` из
        ``infrastructure.sources.file_watcher``.
        Активируется через feature_flag ``eventbus_file_watcher`` (default-OFF).

        Args:
            route_id: Уникальный ID маршрута.
            path: Корневой путь (строка или Path). Может комбинироваться с ``paths``.
            paths: Один или несколько путей для наблюдения. Объединяются с ``path``.
            recursive: Рекурсивно обходить поддиректории (default ``True``).
            glob_include: Glob-паттерн(ы), которым должен соответствовать путь.
            glob_exclude: Glob-паттерн(ы), исключающие путь из событий.
            batch_size: Максимальное число событий в одном батче.
            batch_window: Максимальное окно (сек) накопления батча.
            **kwargs: Дополнительные параметры для :class:`FileWatcherSource`
                (debounce, watch_filter).

        Returns:
            RouteBuilder с ``source`` установленным в ``filewatcher:<paths>``.

        Example::

            route = (
                RouteBuilder.from_filewatcher(
                    "config.hotreload",
                    path="/etc/app/config",
                    recursive=False,
                    glob_include="*.yml",
                    batch_size=10,
                    batch_window=1.0,
                )
                .dispatch_action("config.reload")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.file_watcher")
        FileWatcherSource = mod.FileWatcherSource

        normalized: list[Path] = []
        if path is not None:
            normalized.append(Path(path))
        if paths is not None:
            if isinstance(paths, (str, Path)):
                normalized.append(Path(paths))
            else:
                normalized.extend(Path(p) for p in paths)
        if not normalized:
            raise ValueError("from_filewatcher requires at least one path")

        source_instance = FileWatcherSource(
            source_id=kwargs.pop("source_id", route_id),
            paths=normalized,
            recursive=recursive,
            glob_include=glob_include,
            glob_exclude=glob_exclude,
            batch_size=batch_size,
            batch_window=batch_window,
            **kwargs,
        )
        source_label = ";".join(str(p) for p in normalized)
        builder: RouteBuilder = cls(
            route_id=route_id, source=f"filewatcher:{source_label}"
        )
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder
