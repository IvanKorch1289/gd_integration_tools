"""SFTP/FTP клиент для передачи файлов.

Асинхронная обёртка для операций upload/download/list
через SFTP (asyncssh) и FTP (aioftp).

Sprint 17 W1 (b2 partial closure): SFTP-вызовы используют
:func:`_resolve_known_hosts` — strict-mode для production (требуется путь
до ``known_hosts``), skip только в ``dev_light`` (V1 security constraint).

S163 W6: добавлен per-instance Circuit Breaker (canonical pattern из smtp.py).
Каждая network-операция (upload/download/list_dir/download_bytes) обёрнута в
``async with self._breaker.guard():``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.backend.core.config.profile import AppProfileChoices, get_active_profile

# NB: порядок импортов критичен (S163 W3 lesson, см. ftp.py).
# ``core.config.settings`` грузится ПЕРВЫМ — pre-breaks circular import chain
# breaker → core.logging → infrastructure.logging → core.interfaces → breaker.
# ``core.config.profile`` загружается ПОСЛЕ settings, иначе profile не pre-loads core.interfaces.
from src.backend.core.config.settings import settings as _settings  # noqa: F401
from src.backend.core.logging import get_logger
from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry

__all__ = ("BaseSftpClient", "SftpClient", "_resolve_known_hosts", "get_sftp_client")

logger = get_logger(__name__)

# S163 W11: retry helper для data-transfer operations (см. ftp.py W8).
# Module-level decorator (аналогично soap_async.py W10).
try:
    from src.backend.infrastructure.resilience.retry import make_async_retry
except ImportError:  # pragma: no cover
    make_async_retry = None  # type: ignore[assignment]

_sftp_retry = (
    make_async_retry(
        max_attempts=3,
        initial_backoff=1.0,
        multiplier=2.0,
        max_backoff=10.0,
        on=(OSError, ConnectionError, TimeoutError),
    )
    if make_async_retry is not None
    else (lambda f: f)
)


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

    S163 W6: per-instance Circuit Breaker через ``get_breaker_registry()``.
    Дефолт: failure_threshold=5, recovery_timeout=60s.

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
        # S163 W6: per-instance Circuit Breaker (canonical pattern из smtp.py).
        self._breaker = get_breaker_registry().get_or_create(
            "sftp", BreakerSpec(name="sftp", failure_threshold=5, recovery_timeout=60.0)
        )

    @_sftp_retry
    async def _do_upload(self, local_path: str, remote_path: str) -> None:
        """Внутренняя upload-операция с retry-обёрткой."""
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

    async def upload(self, local_path: str, remote_path: str) -> None:
        """Загружает файл на SFTP-сервер.

        Args:
            local_path: Путь к локальному файлу.
            remote_path: Путь на удалённом сервере.
        """
        async with self._breaker.guard():
            await self._do_upload(local_path, remote_path)
            logger.info("SFTP upload: %s → %s:%s", local_path, self.host, remote_path)

    @_sftp_retry
    async def _do_download(self, remote_path: str, local_path: str) -> None:
        """Внутренняя download-операция с retry-обёрткой."""
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

    async def download(self, remote_path: str, local_path: str) -> None:
        """Скачивает файл с SFTP-сервера.

        Args:
            remote_path: Путь на удалённом сервере.
            local_path: Путь для сохранения локально.
        """
        async with self._breaker.guard():
            await self._do_download(remote_path, local_path)
            logger.info("SFTP download: %s:%s → %s", self.host, remote_path, local_path)

    async def list_dir(self, remote_path: str = ".") -> list[dict[str, Any]]:
        """Возвращает список файлов в директории.

        Args:
            remote_path: Путь на удалённом сервере.

        Returns:
            Список словарей с информацией о файлах.
        """
        import asyncssh

        async with self._breaker.guard():
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

    @_sftp_retry
    async def _do_download_bytes(self, remote_path: str) -> bytes:
        """Внутренняя download_bytes-операция с retry-обёрткой."""
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

    async def download_bytes(self, remote_path: str) -> bytes:
        """Скачивает файл как bytes.

        Args:
            remote_path: Путь на удалённом сервере.

        Returns:
            Содержимое файла.
        """
        async with self._breaker.guard():
            return await self._do_download_bytes(remote_path)


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
