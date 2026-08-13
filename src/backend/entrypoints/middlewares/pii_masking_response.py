"""PII masking response middleware (S18 W3, cycle 54 pure ASGI).

Глобальный wrapper, применяющий :class:`core.security.pii_masker.PIIMasker`
к JSON-телам ответов на configurable path patterns. В отличие от
:class:`entrypoints.middlewares.data_masking.DataMaskingMiddleware` (S8A
legacy, локальные regex), этот middleware использует единый
:func:`default_masker` из ``core.security.pii_masker``, что соответствует
плану S22 W1 A-07 «PII Masker Unification».

Поведение:
    * Feature-flag ``pii_response_middleware_enabled`` (default-OFF) —
      при False middleware прозрачен (pass-through).
    * ``path_patterns`` (список regex) ограничивает применение к
      указанным путям. ``None`` или ``[]`` → применять ко всем путям.
    * Применяется только к ответам с ``Content-Type: application/json``.
    * Используется :meth:`PIIMasker.mask_dict` (rekursive).

Cycle 54: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-53 (L1 middlewares).

Cycle 54 critical: response body modification.
В pure ASGI нельзя модифицировать body ПОСЛЕ отправки downstream.
Нужно: suppress original body messages, send new http.response.start
(with updated content-length) + http.response.body с masked body.
"""

import re
from collections.abc import Iterable
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.logging import get_logger
from src.backend.core.security.pii_masker import default_masker

__all__ = ("PIIMaskingResponseMiddleware",)

_logger = get_logger(__name__)


class PIIMaskingResponseMiddleware:
    """Pure ASGI middleware: маскирует PII в JSON-телах ответов (cycle 54).

    Args:
        app: ASGI-приложение.
        path_patterns: Список regex для путей, к которым применять
            маскировку. ``None`` / пустой список — применять ко всем
            путям.

    Notes:
        Feature-flag ``pii_response_middleware_enabled`` (S18 W3 backbone)
        проверяется внутри :meth:`dispatch` lazy-импортом.

    """

    def __init__(
        self, app: ASGIApp, *, path_patterns: Iterable[str] | None = None,
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            path_patterns: Список regex для путей маскировки.

        """
        self.app = app
        self._path_patterns: tuple[re.Pattern[str], ...] = tuple(
            re.compile(p) for p in (path_patterns or ())
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process PII masking for response bodies.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self._is_enabled():
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not self._path_matches(path):
            await self.app(scope, receive, send)
            return

        # Cycle 54 critical: collect body chunks через send-wrapper.
        # Pure ASGI: buffer body messages, apply mask, re-send.
        state: dict = {"should_mask": True, "content_type": ""}
        body_chunks: list[bytes] = []
        original_status: int = 200
        original_headers: list[tuple[bytes, bytes]] = []

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Capture status + headers (для replay).
                nonlocal original_status, original_headers
                original_status = message.get("status", 200)
                original_headers = list(message.get("headers", []))

                # Check content-type + content-encoding перед сбором body.
                # ponytail: инициализируем как str, чтобы ``"application/json" not in content_type``
                # работал и для случая, когда content-type header отсутствует (ранее
                # крашилось с TypeError str-in-bytes).
                content_type = ""
                content_encoding = ""
                for k, v in original_headers:
                    if k.lower() == b"content-type":
                        content_type = v.decode("latin-1", errors="replace")
                    elif k.lower() == b"content-encoding":
                        content_encoding = v.decode("latin-1", errors="replace")
                # D-AUDIT-16601 fix (cycle 166): skip PII masking for:
                # 1. Non-JSON content types (binary endpoints, prometheus)
                # 2. Gzip-compressed responses (GZipMiddleware compresses
                #    /metrics and other binary content → UTF-8 decode fails)
                # Раньше /metrics → 500 'response_masking_failed' (0x8b gzip
                # byte не декодируется как UTF-8 → fallback error).
                is_json = "application/json" in content_type
                is_gzip = "gzip" in content_encoding.lower()
                if not is_json or is_gzip:
                    # Skip PII masking — пробрасываем original.
                    state["should_mask"] = False
                    # Send start immediately (downstream-уже-ждёт).
                    await send(message)
                else:
                    # Suppress original start — мы отправим свой.
                    pass
            elif message["type"] == "http.response.body":
                if state["should_mask"]:
                    # Collect chunks (не отправляем пока).
                    body_chunks.append(message.get("body", b""))
                    # НЕ отправляем сейчас.
                else:
                    # Не маскируем — пробрасываем original.
                    await send(message)
            else:
                await send(message)

        # Пробрасываем downstream (collect body через send_wrapper).
        await self.app(scope, receive, send_wrapper)

        # Если не маскируем — ничего не делаем (original уже отправлен).
        if not state["should_mask"]:
            return

        body = b"".join(body_chunks)
        if not body:
            return

        try:
            masked = self._mask_json_bytes(body)
        except Exception as exc:
            _logger.warning(
                "PIIMaskingResponseMiddleware: ошибка маскировки %s, payload "
                "пропущен без изменений: %s",
                path,
                exc,
            )
            return

        # Cycle 54 critical: send new response (start + body) с masked body.
        # Update content-length в headers.
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
                "status": original_status,
                "headers": new_headers,
            },
        )
        await send({"type": "http.response.body", "body": masked})

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _is_enabled() -> bool:
        """Lazy-проверка feature-flag ``pii_response_middleware_enabled``."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(
                getattr(feature_flags, "pii_response_middleware_enabled", False),
            )
        except (ImportError, AttributeError, RuntimeError) as ff_exc:
            # cycle-9/D-AUDIT-1002: narrow exceptions + observability.
            # ImportError — features module missing, AttributeError —
            # config not initialized, RuntimeError — feature_flags unavailable.
            import logging
            logging.getLogger(__name__).debug(
                "pii_masking_response.feature_flag_fallback",
                extra={"error": str(ff_exc)},
            )
            return False

    def _path_matches(self, path: str) -> bool:
        """True если path matches один из patterns (или patterns пуст)."""
        if not self._path_patterns:
            return True
        return any(p.search(path) for p in self._path_patterns)

    @staticmethod
    def _mask_json_bytes(raw: bytes) -> bytes:
        """Парсит JSON, применяет :meth:`PIIMasker.mask_dict`, сериализует обратно."""
        import orjson

        text = raw.decode("utf-8")
        data: Any = orjson.loads(text)
        masker = default_masker()
        if isinstance(data, dict):
            masked = masker.mask_dict(data)
        else:
            # Top-level list / scalar — обход через приватный recursive helper.
            masked = masker.mask_dict({"_root": data})["_root"]
        return orjson.dumps(masked)
