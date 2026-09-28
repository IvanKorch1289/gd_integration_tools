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

# S219/S221: паттерны PII берутся из канонического single source of truth
# (core.security.pii_patterns), а не дублируются здесь. Локальные копии
# разъехались с каноном: приватный ``_PHONE_RE`` матчил ISO-8601 дату, и
# ``/ready`` отдавал ``"timestamp":"+***0928T15:12:46.355395+00:00"`` —
# дата в ответе readiness-эндпоинта была нечитаема.
#
# Формат вывода остаётся локальным (``a***b@host`` / ``+***1234``) —
# здесь меняется только источник паттерна.
from src.backend.core.security.pii_patterns import EMAIL as _EMAIL_RE
from src.backend.core.security.pii_patterns import PHONE as _PHONE_RE

_logger = get_logger(__name__)

__all__ = (
    "DOCUMENTATION_PATHS",
    "DataMaskingMiddleware",
    "MASKING_EXEMPT_PATHS",
    "TOKEN_ISSUER_PATHS",
)

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

# Prod-fix 2026-09-09 (M6-#3): ответ token-issuer'а — это сам токен;
# маскирование здесь ломало контракт (клиент получал "***" вместо JWT).
#
# Канон для обоих response-маскеров: набор живёт здесь и импортируется
# в pii_masking_response. До 2026-09-28 у того модуля был свой кортеж
# ``("/api/v1/auth/login",)`` — step-up-request в него не попал, и
# ``/api/v1/auth/step-up-request`` отдавал клиенту битый токен:
# PII-регулярка Phone съедала цифровые серии внутри hex-подписи
# (``...e48140c***e***``). На живом прогоне порча воспроизводилась
# примерно в 20% выдач — логин у пользователей падал с
# "step_up_token_required" при верном токене.
TOKEN_ISSUER_PATHS = frozenset({"/api/v1/auth/login", "/api/v1/auth/step-up-request"})

# Документация API маскированию не подлежит.
#
# Найдено на живом сервисе: опубликованная спецификация содержала 16
# значений, испорченных маскированием, — описания полей и summary
# превращались в "***":
#   'Семантический поиск'              -> '*** поиск'          (_RU_SURNAMES)
#   'Логистический маршрут'            -> '*** маршрут'        (_RU_SURNAMES)
#   'Stream ID записи (e.g. +7900...)' -> 'Stream ID ... ***'   (phone)
#   Body_introspect...properties.token -> '***'                (маска по имени ключа)
#
# Спецификация собирается из аннотаций исходного кода: runtime-данных и
# данных арендаторов в ней нет (проверено — все 414 путей статические,
# определения DSL-маршрутов в OpenAPI не попадают). Маскирование здесь не
# даёт выигрыша в приватности, но уничтожает контракт, который читают
# разработчики и сгенерированные из спецификации клиенты.
DOCUMENTATION_PATHS = frozenset(
    {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
)

#: Пути, исключённые из маскирования ответа обоими маскерами.
MASKING_EXEMPT_PATHS = TOKEN_ISSUER_PATHS | DOCUMENTATION_PATHS


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

        # Prod-fix 2026-09-09 (M6-#3): token-issuer endpoints исключены —
        # выдача access_token и есть назначение ответа; маскировка
        # превращала логин в бесполезный {"access_token": "***"}.
        path = scope.get("path", "")
        if path in MASKING_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Collect body chunks через send-wrapper.
        # Cycle 58 critical: pure ASGI send-wrapper pattern для body modification.
        body_chunks: list[bytes] = []
        content_type: dict[str, str] = {"value": ""}
        response_status: dict[str, int] = {"status": 0}
        original_headers: list[tuple[bytes, bytes]] = []
        # D-AUDIT-17201 fix: should_mask flag для non-JSON pass-through.
        # JSON → suppress start, collect body, re-send masked.
        # Non-JSON → pass through both start + body immediately.
        should_mask: bool = True

        async def send_wrapper(message) -> None:  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                response_status["status"] = message.get("status", 200)
                # Capture content-type + headers.
                for k, v in message.get("headers", []):
                    original_headers.append((k, v))
                    if k.lower() == b"content-type":
                        content_type["value"] = v.decode("latin-1", errors="replace")
                # D-AUDIT-17201 fix (cycle 172, retry): for non-JSON
                # responses, pass through original start immediately
                # (BEFORE body) instead of suppressing. Suppressing
                # without re-sending caused ASGI protocol error →
                # 500 'Internal server error' на /docs, /redoc, etc.
                if "application/json" not in content_type["value"]:
                    await send(message)
                # else: Suppress original (JSON, will re-send with masked body)
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
        # D-AUDIT-17201 fix (cycle 172): non-JSON responses передают
        # original start + body через send_wrapper (line 95-100). Здесь
        # ничего не делаем.
        if not should_mask:
            # Non-JSON: original start + body уже отправлены в
            # send_wrapper. Ничего не делаем.
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
            }
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
            return _PHONE_RE.sub(self._mask_phone, result)
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
