"""WebDAV polling source — закрывает GAP INF-2.8 (S13 K3 W2).

Async-source, периодически опрашивает WebDAV-сервер и эмитит ``FileEvent``
для новых файлов. Marker-based dedup: уже обработанные файлы записываются
в персистентный список на сервере (``_processed.txt``), чтобы избежать
повторных эмиссий после restart.

Использует ``webdav4.Client`` (sync API) через ``asyncio.to_thread`` —
аналогично существующему DSL-processor ``webdav_io.py`` (S5 K3 W3).

Поддерживаемые провайдеры: Nextcloud, OwnCloud, любой WebDAV-сервер
RFC 4918 (PROPFIND/GET/PUT).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator

from src.backend.infrastructure.sources.file_watcher import FileEvent

__all__ = ("WebDAVSource", "WebDAVSourceConfig")

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class WebDAVSourceConfig:
    """Декларативный конфиг :class:`WebDAVSource`.

    Args:
        url: Базовый URL WebDAV-сервера.
        watch_path: Папка для опроса.
        poll_interval_seconds: Интервал между PROPFIND-запросами.
        file_pattern: Glob-фильтр имени файла (например, ``"*.csv"``).
        username/password: HTTP basic auth (или mTLS через webdav4 config).
        processed_marker_path: Путь на сервере для записи списка обработанных.
        marker_dedup: Если True — пишет marker на сервере (defense против restart).
    """

    url: str
    watch_path: str = "/"
    poll_interval_seconds: int = 60
    file_pattern: str = "*"
    username: str | None = None
    password: str | None = None
    processed_marker_path: str | None = None
    marker_dedup: bool = True


class WebDAVSource:
    """WebDAV polling-source.

    Метод :meth:`stream` возвращает ``AsyncIterator[FileEvent]``: эмитит
    события ``added`` для каждого нового файла. Прекращает работу при
    отмене задачи (``asyncio.CancelledError`` пробрасывается наружу).
    """

    def __init__(self, config: WebDAVSourceConfig) -> None:
        self._config = config
        self._processed_files: set[str] = set()
        self._closed = False

    def _make_client(self):
        from webdav4.client import Client

        auth: tuple[str, str] | None = None
        if self._config.username and self._config.password:
            auth = (self._config.username, self._config.password)
        return Client(self._config.url, auth=auth)

    def _matches_pattern(self, name: str) -> bool:
        import fnmatch

        return fnmatch.fnmatch(name, self._config.file_pattern)

    def _load_marker(self, client) -> None:
        """Загружает уже обработанные файлы из marker'а на сервере."""
        if not self._config.marker_dedup or not self._config.processed_marker_path:
            return
        try:
            import io

            buf = io.BytesIO()
            client.download_fileobj(self._config.processed_marker_path, buf)
            content = buf.getvalue().decode("utf-8", errors="replace")
            self._processed_files = {
                line.strip() for line in content.splitlines() if line.strip()
            }
        except Exception as _:  # noqa: BLE001
            # Marker не существует — first run.
            self._processed_files = set()

    def _save_marker(self, client) -> None:
        if not self._config.marker_dedup or not self._config.processed_marker_path:
            return
        try:
            import io

            content = "\n".join(sorted(self._processed_files))
            buf = io.BytesIO(content.encode("utf-8"))
            client.upload_fileobj(
                buf, self._config.processed_marker_path, overwrite=True
            )
        except Exception as _:  # noqa: BLE001
            logger.exception("WebDAVSource._save_marker failed")

    def _list_remote_files(self, client) -> list[str]:
        try:
            items = client.ls(self._config.watch_path, detail=False)
            return [str(p) for p in items]
        except Exception as _:  # noqa: BLE001
            logger.exception("WebDAVSource._list_remote_files failed")
            return []

    async def stream(self) -> AsyncIterator[FileEvent]:
        """Polling-генератор событий новых файлов.

        Yields:
            :class:`FileEvent` со ``change_type='added'`` для каждого
            файла, отсутствующего в ``_processed_files``.
        """
        from pathlib import PurePosixPath

        client = await asyncio.to_thread(self._make_client)
        await asyncio.to_thread(self._load_marker, client)

        try:
            while not self._closed:
                paths = await asyncio.to_thread(self._list_remote_files, client)
                new_files = []
                for p in paths:
                    name = PurePosixPath(p).name
                    if not name or not self._matches_pattern(name):
                        continue
                    if p in self._processed_files:
                        continue
                    new_files.append(p)
                    self._processed_files.add(p)

                if new_files:
                    await asyncio.to_thread(self._save_marker, client)

                for p in new_files:
                    yield FileEvent(
                        path=p,  # type: ignore[arg-type,unused-ignore]
                        change_type="added",
                        timestamp=time.time(),
                    )

                try:
                    await asyncio.sleep(self._config.poll_interval_seconds)
                except asyncio.CancelledError:
                    raise
        finally:
            self._closed = True

    async def close(self) -> None:
        """Graceful shutdown."""
        self._closed = True
