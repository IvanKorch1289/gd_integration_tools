from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

class HttpSourcesMixin:
    """HTTP-based source registration (WebDAV) для RouteBuilder. S57 W2 extraction."""

    __slots__ = ()

    @classmethod
    def from_webdav(
        cls,
        route_id: str,
        url: str,
        *,
        watch_path: str = "/",
        poll_interval_seconds: int = 60,
        file_pattern: str = "*",
        username: str | None = None,
        password: str | None = None,
        processed_marker_path: str | None = None,
        marker_dedup: bool = True,
    ) -> RouteBuilder:
        """Создаёт маршрут с polling-источником WebDAV (S13 K3 W2, INF-2.8).

        Args:
            route_id: Уникальный ID маршрута.
            url: Базовый URL WebDAV-сервера (e.g. ``http://nextcloud:80/remote.php/dav/files/admin``).
            watch_path: Папка для опроса.
            poll_interval_seconds: Интервал между PROPFIND-запросами.
            file_pattern: Glob-фильтр имени файла.
            username/password: HTTP basic auth.
            processed_marker_path: Путь на сервере для маркера (опц.).
            marker_dedup: Использовать persistent marker для dedup.

        Returns:
            RouteBuilder с source ``webdav:<route_id>``.
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.webdav")
        cfg = mod.WebDAVSourceConfig(
            url=url,
            watch_path=watch_path,
            poll_interval_seconds=poll_interval_seconds,
            file_pattern=file_pattern,
            username=username,
            password=password,
            processed_marker_path=processed_marker_path,
            marker_dedup=marker_dedup,
        )
        source_instance = mod.WebDAVSource(cfg)
        builder: RouteBuilder = cls(route_id=route_id, source=f"webdav:{route_id}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

