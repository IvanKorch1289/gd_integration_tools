"""SFTP/FTP клиент для передачи файлов.

Асинхронная обёртка для операций upload/download/list
через SFTP (asyncssh) и FTP (aioftp).
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

__all__ = ("BaseSftpClient", "SftpClient", "get_sftp_client")

logger = logging.getLogger(__name__)


class BaseSftpClient(ABC):
    """Абстрактный базовый класс для SFTP-клиентов."""

    @abstractmethod
    async def upload(self, local_path: str, remote_path: str) -> None:
        """Загружает файл на сервер."""

    @abstractmethod
    async def download(self, remote_path: str, local_path: str) -> None:
        """Скачивает файл с сервера."""

    @abstractmethod
    async def list_dir(self, remote_path: str = ".") -> list[dict[str, Any]]:
        """Возвращает список файлов в директории."""


class SftpClient(BaseSftpClient):
    """Асинхронный SFTP-клиент.

    Attrs:
        host: Адрес SFTP-сервера.
        port: Порт (22 по умолчанию).
        username: Логин.
        password: Пароль.
    """

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "",
        password: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    async def upload(
        self,
        local_path: str,
        remote_path: str,
    ) -> None:
        """Загружает файл на SFTP-сервер.

        Args:
            local_path: Путь к локальному файлу.
            remote_path: Путь на удалённом сервере.
        """
        import asyncssh

        async with asyncssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            known_hosts=None,
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                await sftp.put(local_path, remote_path)
                logger.info(
                    "SFTP upload: %s → %s:%s",
                    local_path,
                    self.host,
                    remote_path,
                )

    async def download(
        self,
        remote_path: str,
        local_path: str,
    ) -> None:
        """Скачивает файл с SFTP-сервера.

        Args:
            remote_path: Путь на удалённом сервере.
            local_path: Путь для сохранения локально.
        """
        import asyncssh

        async with asyncssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            known_hosts=None,
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                await sftp.get(remote_path, local_path)
                logger.info(
                    "SFTP download: %s:%s → %s",
                    self.host,
                    remote_path,
                    local_path,
                )

    async def list_dir(
        self,
        remote_path: str = ".",
    ) -> list[dict[str, Any]]:
        """Возвращает список файлов в директории.

        Args:
            remote_path: Путь на удалённом сервере.

        Returns:
            Список словарей с информацией о файлах.
        """
        import asyncssh

        async with asyncssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            known_hosts=None,
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                entries = await sftp.readdir(remote_path)
                return [
                    {
                        "filename": entry.filename,
                        "size": entry.attrs.size
                        if entry.attrs
                        else None,
                        "modified": str(entry.attrs.mtime)
                        if entry.attrs and entry.attrs.mtime
                        else None,
                    }
                    for entry in entries
                    if entry.filename not in (".", "..")
                ]

    async def download_bytes(
        self,
        remote_path: str,
    ) -> bytes:
        """Скачивает файл как bytes.

        Args:
            remote_path: Путь на удалённом сервере.

        Returns:
            Содержимое файла.
        """
        import asyncssh

        async with asyncssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            known_hosts=None,
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(remote_path, "rb") as f:
                    return await f.read()


def get_sftp_client(
    host: str,
    port: int = 22,
    username: str = "",
    password: str = "",
) -> SftpClient:
    """Создаёт SFTP-клиент.

    Args:
        host: Адрес сервера.
        port: Порт.
        username: Логин.
        password: Пароль.

    Returns:
        Экземпляр ``SftpClient``.
    """
    return SftpClient(
        host=host,
        port=port,
        username=username,
        password=password,
    )
