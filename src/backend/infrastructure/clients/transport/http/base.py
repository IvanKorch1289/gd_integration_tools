from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from functools import lru_cache
from logging import DEBUG
from time import monotonic
from typing import Any, BinaryIO, TypedDict

import httpx
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.backend.core.config.constants import consts
from src.backend.core.config.settings import settings
from src.backend.core.utils.circuit_breaker import get_circuit_breaker
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.dsl.codec.json import json_dumps
from src.backend.infrastructure.logging.factory import get_logger

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
