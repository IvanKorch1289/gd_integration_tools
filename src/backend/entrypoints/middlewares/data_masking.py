"""Middleware для маскировки персональных данных (PII) в ответах (cycle 58 pure ASGI, ФИНАЛЬНАЯ L1).

Маскирует email, телефон, пароль и другие чувствительные поля
в JSON-ответах перед отправкой клиенту. Применяется только
к ответам с Content-Type: application/json.

Cycle 58: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-57 (L1 middlewares).
ЭТО ФИНАЛЬНАЯ большая L1 миграция (после cycle 57 CSRF).

Cycle 58 design: response body modification через suppress+resend
pattern (аналог cycle 54 PIIMaskingResponse, но с body modification).
Middleware:
1. Collect body chunks через send-wrapper.
2. Apply mask to body (replace sensitive keys with ***, mask email/phone).
3. Suppress original start + body.
4. Send new start (с updated content-length) + new body.

В BaseHTTPMiddleware версии middleware использовал
``response.body_iterator = AsyncChunkIterator([masked])`` (магический
Starlette API). В pure ASGI нет body_iterator — нужно
suppress+resend (аналог cycle 54 PII).
"""

import re
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)

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
    },
)


class DataMaskingMiddleware:
    """Pure ASGI middleware: маскирует PII в JSON-ответах (cycle 58)."""

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.

        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process data masking for response bodies.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Collect body chunks через send-wrapper.
        # Cycle 58 critical: pure ASGI send-wrapper pattern для body modification.
        body_chunks: list[bytes] = []
        content_type: dict[str, str] = {"value": ""}
        response_status: dict[str, int] = {"status": 0}
        original_headers: list[tuple[bytes, bytes]] = []

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message.get("status", 200)
                # Capture content-type + headers.
                for k, v in message.get("headers", []):
                    original_headers.append((k, v))
                    if k.lower() == b"content-type":
                        content_type["value"] = v.decode(
                            "latin-1", errors="replace",
                        )
                # Suppress original — отправим свой с masked body
                # (cycle 58 invariant: suppress всегда для content-length update).
            elif message["type"] == "http.response.body":
                if "application/json" in content_type["value"]:
                    # JSON: collect body для masking.
                    body_chunks.append(message.get("body", b""))
                else:
                    # Non-JSON: pass through unchanged (no-need to mask).
                    await send(message)
            else:
                await send(message)

        # Пробрасываем downstream (collect body через send_wrapper).
        await self.app(scope, receive, send_wrapper)

        # Skip non-JSON content type (уже пробрасывали в send_wrapper).
        if "application/json" not in content_type["value"]:
            return

        body = b"".join(body_chunks)
        if not body:
            return

        # Apply mask.
        try:
            masked = self._mask_bytes(body)
        except Exception as exc:
            # ponytail: fail-closed на PII (cycle 78 L1 invariant).
            # При ошибке маскировки возвращаем masked error response
            # вместо unmasked body (security > availability).
            _logger.exception(
                "data_masking failed; returning masked error response instead of unmasked body: %s",
                exc,
            )
            masked = self._mask_bytes_fallback()

        # Cycle 58: send new response с masked body + updated headers.
        new_headers: list[tuple[bytes, bytes]] = []
        for k, v in original_headers:
            if k.lower() == b"content-length":
                # Skip — добавим с новым значением.
                continue
            new_headers.append((k, v))
        new_headers.append((b"content-length", str(len(masked)).encode("latin-1")))

        await send(
            {
                "type": "http.response.start",
                "status": response_status["status"],
                "headers": new_headers,
            },
        )
        await send({"type": "http.response.body", "body": masked})

    def _mask_bytes(self, raw: bytes) -> bytes:
        """Маскирует PII в JSON-байтах."""
        import orjson

        text = raw.decode("utf-8")
        data = orjson.loads(text)
        masked = self._mask_value(data)
        return orjson.dumps(masked)

    def _mask_bytes_fallback(self) -> bytes:
        """Fail-closed fallback: при ошибке маскировки заменяем весь body на error marker."""
        import orjson

        error_body = {
            "error": "response_masking_failed",
            "detail": "PII masking failed; original response withheld for safety",
        }
        return orjson.dumps(error_body)

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
        return f"+***{digits[-4:]}"
