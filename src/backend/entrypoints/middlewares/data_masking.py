"""Middleware для маскировки персональных данных (PII) в ответах.

Маскирует email, телефон, пароль и другие чувствительные поля
в JSON-ответах перед отправкой клиенту. Применяется только
к ответам с Content-Type: application/json.
"""

import re
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from src.backend.core.utils.async_helpers import AsyncChunkIterator

__all__ = ("DataMaskingMiddleware",)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
    }
)


class DataMaskingMiddleware(BaseHTTPMiddleware):
    """Маскирует PII в JSON-ответах."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = await self._capture_body(response)

        try:
            masked = self._mask_bytes(body)
            response.headers["content-length"] = str(len(masked))
            response.body_iterator = AsyncChunkIterator([masked])  # type: ignore
        except Exception:
            response.body_iterator = AsyncChunkIterator([body])  # type: ignore

        return response

    def _mask_bytes(self, raw: bytes) -> bytes:
        """Маскирует PII в JSON-байтах."""
        import orjson

        text = raw.decode("utf-8")
        try:
            data = orjson.loads(text)
            masked = self._mask_value(data)
            return orjson.dumps(masked)
        except orjson.JSONDecodeError, UnicodeDecodeError:
            return raw

    def _mask_value(self, obj: Any) -> Any:
        """Рекурсивно маскирует чувствительные значения."""
        if isinstance(obj, dict):
            return {
                k: "***" if k.lower() in _SENSITIVE_KEYS else self._mask_value(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [self._mask_value(item) for item in obj]
        if isinstance(obj, str):
            result = _EMAIL_RE.sub(self._mask_email, obj)
            result = _PHONE_RE.sub(self._mask_phone, result)
            return result
        return obj

    @staticmethod
    def _mask_email(match: re.Match) -> str:
        email = match.group(0)
        local, domain = email.rsplit("@", 1)
        if len(local) <= 2:
            return f"**@{domain}"
        return f"{local[0]}***{local[-1]}@{domain}"

    @staticmethod
    def _mask_phone(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) <= 4:
            return match.group(0)
        return digits[:2] + "*" * (len(digits) - 4) + digits[-2:]

    @staticmethod
    async def _capture_body(response: Response) -> bytes:
        chunks = []
        async for chunk in response.body_iterator:  # type: ignore
            chunks.append(chunk)
        return b"".join(chunks)
