"""Async FTP/FTPS client — upload, download, list, delete."""

from __future__ import annotations

import logging
import ssl
from pathlib import PurePosixPath
from typing import Any

__all__ = ("FTPClient", "get_ftp_client")

logger = logging.getLogger(__name__)


class FTPClient:
    """Асинхронный FTP/FTPS клиент на основе aioftp.

    Поддерживает:
    - Plain FTP и FTPS (explicit/implicit TLS)
    - Upload/download файлов
    - Directory listing
    - Delete/rename
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

    async def connect(self) -> None:
        """Устанавливает FTP-соединение."""
        import aioftp

        ssl_context = None
        if self._use_tls:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

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
        """Закрывает FTP-соединение."""
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
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        return aioftp.Client.context(
            self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            ssl=ssl_context,
            encoding=self._encoding,
        )

    async def upload(self, local_path: str, remote_path: str) -> None:
        """Загружает файл на FTP-сервер."""
        async with await self._get_client() as client:
            remote = PurePosixPath(remote_path)
            parent = remote.parent
            if str(parent) != ".":
                await client.make_directory(parent, parents=True)
            await client.upload(local_path, remote_path, write_into=True)
            logger.info("Uploaded %s -> %s", local_path, remote_path)

    async def upload_bytes(self, data: bytes, remote_path: str) -> None:
        """Загружает bytes на FTP-сервер."""

        async with await self._get_client() as client:
            remote = PurePosixPath(remote_path)
            parent = remote.parent
            if str(parent) != ".":
                await client.make_directory(parent, parents=True)

            async with client.upload_stream(remote_path) as stream:
                await stream.write(data)

            logger.info("Uploaded %d bytes -> %s", len(data), remote_path)

    async def download(self, remote_path: str, local_path: str) -> None:
        """Скачивает файл с FTP-сервера."""
        async with await self._get_client() as client:
            await client.download(remote_path, local_path, write_into=True)
            logger.info("Downloaded %s -> %s", remote_path, local_path)

    async def download_bytes(self, remote_path: str) -> bytes:
        """Скачивает файл в память."""
        import io

        buffer = io.BytesIO()
        async with await self._get_client() as client:
            async with client.download_stream(remote_path) as stream:
                async for block in stream.iter_by_block():
                    buffer.write(block)
        return buffer.getvalue()

    async def list_dir(self, path: str = "/") -> list[dict[str, Any]]:
        """Список файлов в директории."""
        result: list[dict[str, Any]] = []
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
        async with await self._get_client() as client:
            await client.remove(remote_path)
            logger.info("Deleted %s", remote_path)

    async def rename(self, old_path: str, new_path: str) -> None:
        """Переименовывает файл."""
        async with await self._get_client() as client:
            await client.rename(old_path, new_path)
            logger.info("Renamed %s -> %s", old_path, new_path)

    async def exists(self, remote_path: str) -> bool:
        """Проверяет существование файла."""
        async with await self._get_client() as client:
            return await client.exists(remote_path)

    async def ping(self) -> bool:
        """Проверка доступности FTP-сервера."""
        try:
            async with await self._get_client():
                return True
        except ConnectionError, TimeoutError, OSError:
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
