from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

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

class ObservabilityMixin:
    """observability (log request/response, update metrics, process response) для HttpClient. S61 W4 extraction."""

    __slots__ = ()

    async def _log_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        data: dict[str, Any] | str | bytes | None,
        files: Mapping[str, FilePart] | None,
    ) -> None:
        safe_headers = {
            key: (
                "***MASKED***"
                if key.lower()
                in {
                    "authorization",
                    "cookie",
                    "set-cookie",
                    "x-api-key",
                    "proxy-authorization",
                }
                else value
            )
            for key, value in headers.items()
        }
        truncated_data = data
        if isinstance(data, (str, bytes)):
            data_as_str = (
                data.decode("utf-8", errors="replace")
                if isinstance(data, bytes)
                else data
            )
            truncated_data = (
                data_as_str[:200] + "..." if len(data_as_str) > 200 else data_as_str
            )
        files_info = None
        if files:
            files_info = {}
            for field_name, file_part in files.items():
                content = file_part.get("content")
                size = len(content) if isinstance(content, (bytes, bytearray)) else None
                files_info[field_name] = {
                    "filename": file_part.get("filename"),
                    "content_type": file_part.get("content_type"),
                    "size": size,
                }
        self.logger.debug(
            "Выполнение HTTP-запроса",
            extra={
                "method": method.upper(),
                "url": url,
                "headers": safe_headers,
                "params": params,
                "data": truncated_data if files is None else None,
                "files": files_info,
            },
        )

    async def _log_response(self, response: httpx.Response, content: Any) -> None:
        content_repr = str(content)
        if len(content_repr) > 500:
            content_repr = content_repr[:500] + "..."
        self.logger.debug(
            "Получен HTTP-ответ",
            extra={
                "status": response.status_code,
                "headers": dict(response.headers),
                "content": content_repr,
            },
        )

    async def _update_metrics(self, start_time: float, success: bool) -> None:
        duration = monotonic() - start_time
        self.metrics["total_requests"] += 1
        key = "successful_requests" if success else "failed_requests"
        self.metrics[key] += 1
        self.metrics["average_response_time"] = (
            0.9 * self.metrics["average_response_time"] + 0.1 * duration
        )

    async def _process_response(
        self, response: httpx.Response, response_type: str
    ) -> Any:
        if response_type == "bytes":
            return response.content
        if response_type == "text":
            return response.text
        if response_type == "json":
            return response.json()
        if response_type == "auto":
            content_type = response.headers.get("Content-Type", "").lower()
            if "json" in content_type:
                return response.json()
            return response.text
        raise ValueError(f"Неподдерживаемый тип ответа: {response_type}")

