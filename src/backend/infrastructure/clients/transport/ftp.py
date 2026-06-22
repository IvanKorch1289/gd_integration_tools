"""Async FTP/FTPS client — upload, download, list, delete.

S163 W3 (R2): добавлен Circuit Breaker (canonical pattern из smtp.py).
- Breaker регистрируется через ``get_breaker_registry().get_or_create('ftp', ...)``
- Каждая сетевая операция обёрнута в ``async with self._breaker.guard():``
- ``ping()`` корректно обрабатывает ``CircuitOpen`` → возвращает ``False``
- Lifecycle-методы (``connect``/``close``) НЕ оборачиваются — это инициализация,
  а не сетевая операция.
"""

from __future__ import annotations

import ssl
from pathlib import PurePosixPath
from typing import Any

# NB: порядок импортов критичен (S163 W3 lesson).
# ``core.config.settings`` грузится ПЕРВЫМ — это pre-loads ``core.interfaces``,
# который импортирует ``core.resilience.breaker``. Без этого ftp.py trigger-ит
# circular import через chain:
#   ftp → breaker → core.logging → infrastructure.logging → core.interfaces → breaker.
# Тот же pattern в smtp.py:12-17.
from src.backend.core.config.settings import settings as _settings  # noqa: F401
from src.backend.core.resilience.breaker import (
    BreakerSpec,
    CircuitOpen,
    get_breaker_registry,
)
from src.backend.core.logging import get_logger
__all__ = ("FTPClient", "get_ftp_client")

logger = get_logger(__name__)

# S163 W8: retry для data-transfer operations (upload/download). Pattern из
# smtp.py:233-241. list_dir/delete/rename/exists/ping — без retry (control
# operations, retry может маскировать реальные ошибки).
# Exceptions: aioftp использует OSError для connection issues, asyncio
# TimeoutError — для timeout, ConnectionError — для refused connection.
try:
    from src.backend.infrastructure.resilience.retry import make_async_retry
except ImportError:  # pragma: no cover
    make_async_retry = None  # type: ignore[assignment]


def _ftp_retry():
    """Фабрика retry-декоратора для FTP data-transfer операций.

    3 попытки, exponential backoff 1s → 2s → 4s (capped at 10s).
    Retry при OSError / ConnectionError / TimeoutError (transient failures).
    """
    if make_async_retry is None:  # pragma: no cover
        return lambda f: f
    return make_async_retry(
        max_attempts=3,
        initial_backoff=1.0,
        multiplier=2.0,
        max_backoff=10.0,
        on=(OSError, ConnectionError, TimeoutError),
    )


class FTPClient:
    """Асинхронный FTP/FTPS клиент на основе aioftp.

    Поддерживает:
    - Plain FTP и FTPS (explicit/implicit TLS)
    - Upload/download файлов
    - Directory listing
    - Delete/rename

    S163 W3: Circuit Breaker через ``get_breaker_registry()`` — canonical pattern.
    Дефолтные параметры: failure_threshold=5, recovery_timeout=60s.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 21,
        user: str = "anonymous",
        password: str = "",
        use_tls: bool = False,
        passive_mode: bool = True,
        encoding: str = "utf-8",
        connect_timeout: int = 30,
        circuit_breaker_max_failures: int = 5,
        circuit_breaker_reset_timeout: float = 60.0,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._use_tls = use_tls
        self._passive_mode = passive_mode
        self._encoding = encoding
        self._connect_timeout = connect_timeout
        self._client: Any = None
        self._breaker = get_breaker_registry().get_or_create(
            "ftp",
            BreakerSpec(
                name="ftp",
                failure_threshold=circuit_breaker_max_failures,
                recovery_timeout=circuit_breaker_reset_timeout,
            ),
        )

    async def connect(self) -> None:
        """Устанавливает FTP-соединение (lifecycle — без breaker)."""
        import aioftp

        ssl_context = None
        if self._use_tls:
            ssl_context = ssl.create_default_context()

        self._client = aioftp.Client.context(
            self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            ssl=ssl_context,
            encoding=self._encoding,
        )
        logger.info(
            "FTP connected to %s:%d (TLS=%s)", self._host, self._port, self._use_tls
        )

    async def close(self) -> None:
        """Закрывает FTP-соединение (lifecycle — без breaker)."""
        if self._client:
            try:
                await self._client.quit()
            except OSError:
                pass
            self._client = None
            logger.info("FTP disconnected")

    async def _get_client(self) -> Any:
        import aioftp

        ssl_context = None
        if self._use_tls:
            ssl_context = ssl.create_default_context()

        return aioftp.Client.context(
            self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            ssl=ssl_context,
            encoding=self._encoding,
        )

    @_ftp_retry()
    async def _do_upload(self, local_path: str, remote_path: str) -> None:
        """Внутренняя upload-операция с retry-обёрткой."""
        async with await self._get_client() as client:
            remote = PurePosixPath(remote_path)
            parent = remote.parent
            if str(parent) != ".":
                await client.make_directory(parent, parents=True)
            await client.upload(local_path, remote_path, write_into=True)

    async def upload(self, local_path: str, remote_path: str) -> None:
        """Загружает файл на FTP-сервер."""
        async with self._breaker.guard():
            await self._do_upload(local_path, remote_path)
            logger.info("Uploaded %s -> %s", local_path, remote_path)

    @_ftp_retry()
    async def _do_upload_bytes(self, data: bytes, remote_path: str) -> None:
        """Внутренняя upload_bytes-операция с retry-обёрткой."""
        async with await self._get_client() as client:
            remote = PurePosixPath(remote_path)
            parent = remote.parent
            if str(parent) != ".":
                await client.make_directory(parent, parents=True)
            async with client.upload_stream(remote_path) as stream:
                await stream.write(data)

    async def upload_bytes(self, data: bytes, remote_path: str) -> None:
        """Загружает bytes на FTP-сервер."""
        async with self._breaker.guard():
            await self._do_upload_bytes(data, remote_path)
            logger.info("Uploaded %d bytes -> %s", len(data), remote_path)

    @_ftp_retry()
    async def _do_download(self, remote_path: str, local_path: str) -> None:
        """Внутренняя download-операция с retry-обёрткой."""
        async with await self._get_client() as client:
            await client.download(remote_path, local_path, write_into=True)

    async def download(self, remote_path: str, local_path: str) -> None:
        """Скачивает файл с FTP-сервера."""
        async with self._breaker.guard():
            await self._do_download(remote_path, local_path)
            logger.info("Downloaded %s -> %s", remote_path, local_path)

    @_ftp_retry()
    async def _do_download_bytes(self, remote_path: str) -> bytes:
        """Внутренняя download_bytes-операция с retry-обёрткой."""
        import io

        buffer = io.BytesIO()
        async with await self._get_client() as client:
            async with client.download_stream(remote_path) as stream:
                async for block in stream.iter_by_block():
                    buffer.write(block)
        return buffer.getvalue()

    async def download_bytes(self, remote_path: str) -> bytes:
        """Скачивает файл в память."""
        async with self._breaker.guard():
            return await self._do_download_bytes(remote_path)

    async def list_dir(self, path: str = "/") -> list[dict[str, Any]]:
        """Список файлов в директории."""
        result: list[dict[str, Any]] = []
        async with self._breaker.guard():
            async with await self._get_client() as client:
                async for entry_path, info in client.list(path):
                    result.append(
                        {
                            "name": str(entry_path),
                            "type": info.get("type", "unknown"),
                            "size": int(info.get("size", 0)),
                            "modify": info.get("modify"),
                        }
                    )
        return result

    async def delete(self, remote_path: str) -> None:
        """Удаляет файл на FTP-сервере."""
        async with self._breaker.guard():
            async with await self._get_client() as client:
                await client.remove(remote_path)
                logger.info("Deleted %s", remote_path)

    async def rename(self, old_path: str, new_path: str) -> None:
        """Переименовывает файл."""
        async with self._breaker.guard():
            async with await self._get_client() as client:
                await client.rename(old_path, new_path)
                logger.info("Renamed %s -> %s", old_path, new_path)

    async def exists(self, remote_path: str) -> bool:
        """Проверяет существование файла."""
        async with self._breaker.guard():
            async with await self._get_client() as client:
                return await client.exists(remote_path)

    async def ping(self) -> bool:
        """Проверка доступности FTP-сервера (CircuitOpen → False)."""
        try:
            async with self._breaker.guard():
                async with await self._get_client():
                    return True
        except (ConnectionError, TimeoutError, OSError, CircuitOpen):
            return False


def get_ftp_client(
    host: str = "localhost",
    port: int = 21,
    user: str = "anonymous",
    password: str = "",
    use_tls: bool = False,
) -> FTPClient:
    """Factory для FTP-клиента (stateless, создаёт новый экземпляр)."""
    return FTPClient(
        host=host, port=port, user=user, password=password, use_tls=use_tls
    )
