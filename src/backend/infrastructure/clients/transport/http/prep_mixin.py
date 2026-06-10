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

class PrepMixin:
    """request prep (build headers, build kwargs, build response object) для HttpClient. S61 W4 extraction."""

    __slots__ = ()

    async def _build_headers(
        self,
        auth_token: str | None,
        custom_headers: dict[str, str] | None,
        json_data: dict[str, Any] | list[Any] | None,
        data: dict[str, Any] | str | bytes | None,
        files: Mapping[str, FilePart] | None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": "HttpClient/2.0",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if custom_headers:
            headers.update(custom_headers)

        has_content_type = any(key.lower() == "content-type" for key in headers)
        if not has_content_type:
            if json_data is not None:
                headers["Content-Type"] = "application/json"
            elif isinstance(data, (str, bytes)):
                headers["Content-Type"] = "application/octet-stream"

        if files:
            # multipart Content-Type httpx выставит сам с правильным boundary.
            headers.pop("Content-Type", None)
        return headers

    async def _prepare_request_kwargs(
        self,
        data: dict[str, Any] | str | bytes | None,
        json_data: dict[str, Any] | list[Any] | None,
        files: Mapping[str, FilePart] | None,
    ) -> dict[str, Any]:
        """Готовит httpx-совместимые kwargs (``content`` / ``data`` / ``files``)."""
        if json_data is not None and (data is not None or files is not None):
            raise ValueError("json нельзя передавать вместе с data/files")

        if files:
            httpx_files: dict[str, tuple[str, Any, str]] = {}
            for field_name, file_part in files.items():
                httpx_files[field_name] = (
                    file_part.get("filename", field_name),
                    file_part["content"],
                    file_part.get("content_type", "application/octet-stream"),
                )
            kwargs: dict[str, Any] = {"files": httpx_files}
            if isinstance(data, dict):
                kwargs["data"] = {
                    key: ("" if value is None else str(value))
                    for key, value in data.items()
                }
            return kwargs

        if json_data is not None:
            return {"content": json_dumps(json_data)}
        if isinstance(data, dict):
            return {"data": data}
        if isinstance(data, (str, bytes)):
            return {"content": data}
        return {}

    async def _build_response_object(
        self, response: httpx.Response, content: Any, start_time: float
    ) -> dict[str, Any]:
        content_type = (
            response.headers.get("Content-Type", "").lower().split(";")[0].strip()
        )
        return {
            "status_code": response.status_code,
            "data": content,
            "headers": dict(response.headers),
            "content_type": content_type,
            "elapsed": monotonic() - start_time,
        }

