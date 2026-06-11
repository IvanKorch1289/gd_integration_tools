from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, BinaryIO, TypedDict


class FilePart(TypedDict, total=False):
    content: bytes | bytearray | BinaryIO
    filename: str
    content_type: str


class BaseHttpClient(ABC):
    """Абстрактный базовый класс для HTTP-клиентов."""

    @abstractmethod
    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | str | bytes | None = None,
        files: Mapping[str, FilePart] | None = None,
        auth_token: str | None = None,
        response_type: str = "auto",
        raise_for_status: bool = True,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        total_timeout: float | None = None,
    ) -> dict[str, Any]:
        """Выполняет HTTP-запрос."""

    @abstractmethod
    async def close(self) -> None:
        """Закрывает соединения."""
