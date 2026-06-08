"""SFTP/FTP клиент для передачи файлов.

Асинхронная обёртка для операций upload/download/list
через SFTP (asyncssh) и FTP (aioftp).

Sprint 17 W1 (b2 partial closure): SFTP-вызовы используют
:func:`_resolve_known_hosts` — strict-mode для production (требуется путь
до ``known_hosts``), skip только в ``dev_light`` (V1 security constraint).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.backend.core.config.profile import AppProfileChoices, get_active_profile
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("BaseSftpClient", "SftpClient", "_resolve_known_hosts", "get_sftp_client")

logger = get_logger(__name__)


def _resolve_known_hosts() -> tuple[()] | str:
    """Возвращает значение ``known_hosts`` для ``asyncssh.connect``.

    Логика:
        * Если ``settings.transport.sftp_known_hosts_path`` задан —
          возвращает строку пути (asyncssh подгружает файл сам).
        * Если путь не задан И активный профиль ``dev_light`` —
          возвращает ``()`` (skip-валидация, безопасно для лок-разработки).
        * Если путь не задан в production-профиле — поднимает
          ``ValueError`` (V1 запрещает отключение проверок без явной
          декларации).

    Returns:
        Путь до ``known_hosts``-файла либо пустой tuple для skip-режима.

    Raises:
        ValueError: путь не задан в non-dev_light-профиле.
    """
    # Локальный импорт settings — избегает циклов на старте модуля.
    from src.backend.core.config.settings import settings

    path = settings.transport.sftp_known_hosts_path
    if path:
        return path
    if get_active_profile() == AppProfileChoices.dev_light:
        return ()
    raise ValueError(
        "TRANSPORT_SFTP_KNOWN_HOSTS_PATH обязателен в профиле "
        f"'{get_active_profile().value}' (V1: запрещено отключать проверку "
        "серверного ключа SFTP без явной декларации)."
    )


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
        self, host: str, port: int = 22, username: str = "", password: str = ""
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    async def upload(self, local_path: str, remote_path: str) -> None:
        """Загружает файл на SFTP-сервер.

        Args:
            local_path: Путь к локальному файлу.
            remote_path: Путь на удалённом сервере.
        """
        import asyncssh

        async with (
            asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                known_hosts=_resolve_known_hosts(),
            ) as conn,
            conn.start_sftp_client() as sftp,
        ):
            await sftp.put(local_path, remote_path)
            logger.info("SFTP upload: %s → %s:%s", local_path, self.host, remote_path)

    async def download(self, remote_path: str, local_path: str) -> None:
        """Скачивает файл с SFTP-сервера.

        Args:
            remote_path: Путь на удалённом сервере.
            local_path: Путь для сохранения локально.
        """
        import asyncssh

        async with (
            asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                known_hosts=_resolve_known_hosts(),
            ) as conn,
            conn.start_sftp_client() as sftp,
        ):
            await sftp.get(remote_path, local_path)
            logger.info("SFTP download: %s:%s → %s", self.host, remote_path, local_path)

    async def list_dir(self, remote_path: str = ".") -> list[dict[str, Any]]:
        """Возвращает список файлов в директории.

        Args:
            remote_path: Путь на удалённом сервере.

        Returns:
            Список словарей с информацией о файлах.
        """
        import asyncssh

        async with (
            asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                known_hosts=_resolve_known_hosts(),
            ) as conn,
            conn.start_sftp_client() as sftp,
        ):
            entries = await sftp.readdir(remote_path)
            return [
                {
                    "filename": entry.filename,
                    "size": entry.attrs.size if entry.attrs else None,
                    "modified": str(entry.attrs.mtime)
                    if entry.attrs and entry.attrs.mtime
                    else None,
                }
                for entry in entries
                if entry.filename not in (".", "..")
            ]

    async def download_bytes(self, remote_path: str) -> bytes:
        """Скачивает файл как bytes.

        Args:
            remote_path: Путь на удалённом сервере.

        Returns:
            Содержимое файла.
        """
        import asyncssh

        async with (
            asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                known_hosts=_resolve_known_hosts(),
            ) as conn,
            conn.start_sftp_client() as sftp,
            sftp.open(remote_path, "rb") as f,
        ):
            return await f.read()


def get_sftp_client(
    host: str, port: int = 22, username: str = "", password: str = ""
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
    return SftpClient(host=host, port=port, username=username, password=password)
