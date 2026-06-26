"""Cert file watcher + hot-reload (S171 M16).

При изменении/добавлении/удалении .pem/.crt файла в cert_watch_path
CertStore автоматически обновляется + уведомляет подписчиков через
``subscribe_updates``.

Pattern (Ponytail, D245): тонкий wrapper вокруг ``watchfiles.awatch``.

Использование::

    watcher = CertFileWatcher(path=Path("/etc/certs"), store=cert_store)
    await watcher.start()  # запускает background task
    # ... добавьте/удалите .pem файлы — store обновится автоматически
    await watcher.stop()
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.infrastructure.security.cert_store.store import CertStore

_logger = get_logger("security.cert_hot_reload")

__all__ = ("CertFileWatcher",)


class CertFileWatcher:
    """File watcher для cert директории.

    Отслеживает добавление/изменение/удаление .pem/.crt файлов через
    ``watchfiles.awatch`` (rust-based, кросс-платформенный).

    Args:
        path: Директория для наблюдения.
        store: :class:`CertStore` для обновления.
        extensions: Расширения файлов для обработки (default: .pem, .crt).
    """

    DEFAULT_EXTENSIONS: tuple[str, ...] = (".pem", ".crt")

    def __init__(
        self,
        *,
        path: Path,
        store: "CertStore",
        extensions: tuple[str, ...] | None = None,
    ) -> None:
        self.path = path
        self.store = store
        self.extensions = extensions or self.DEFAULT_EXTENSIONS
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def _should_handle(self, file_path: Path) -> bool:
        """Проверить, нужно ли обрабатывать событие для этого файла."""
        return file_path.suffix.lower() in self.extensions

    def _cert_id_from_path(self, file_path: Path) -> str:
        """cert_id = filename без расширения (для CertStore.set/delete)."""
        return file_path.stem

    async def _on_file_event(
        self, file_path: Path, event_type: str
    ) -> None:
        """Обработать событие файла (add/modify/delete)."""
        if not self._should_handle(file_path):
            return
        cert_id = self._cert_id_from_path(file_path)
        try:
            if event_type == "delete":
                await self.store.delete(cert_id)
                _logger.info("cert.hot_reload.delete id=%s", cert_id)
            else:
                # add или modify
                pem = file_path.read_text(encoding="utf-8")
                await self.store.set(cert_id, pem=pem)
                _logger.info(
                    "cert.hot_reload.%s id=%s size=%d",
                    event_type, cert_id, len(pem),
                )
        except Exception as exc:
            _logger.warning(
                "cert.hot_reload.error id=%s event=%s: %s",
                cert_id, event_type, exc,
            )

    async def _watch_loop(self) -> None:
        """Основной цикл watchfiles.awatch (rust-based)."""
        from watchfiles import awatch

        _logger.info(
            "cert.hot_reload.start path=%s extensions=%s",
            self.path, self.extensions,
        )
        try:
            async for changes in awatch(
                self.path,
                stop_event=self._stop_event,
                recursive=False,
            ):
                for change_type, file_path_str in changes:
                    # change_type: 1=added, 2=modified, 3=deleted
                    type_name = {1: "add", 2: "modify", 3: "delete"}.get(
                        change_type, "unknown"
                    )
                    file_path = Path(file_path_str)
                    await self._on_file_event(file_path, type_name)
        except asyncio.CancelledError:
            _logger.info("cert.hot_reload.cancelled")
            raise
        except Exception as exc:
            _logger.error("cert.hot_reload.loop_error: %s", exc)
            raise

    async def start(self) -> None:
        """Запустить watcher как background task."""
        if self._task is not None:
            _logger.warning("cert.hot_reload.already_started")
            return
        if not self.path.exists():
            self.path.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._watch_loop(), name=f"cert-watcher-{self.path.name}"
        )
        _logger.info("cert.hot_reload.task_started")

    async def stop(self) -> None:
        """Остановить watcher gracefully."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None
        _logger.info("cert.hot_reload.stopped")
