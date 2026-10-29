"""Middleware для логирования входящих запросов и исходящих ответов (cycle 53 pure ASGI).

Логирует метод запроса, URL, тело запроса (если включено), статус ответа,
время обработки и тело ответа (если включено). Поддерживает обработку
сжатых данных (gzip).

Cycle 53: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-52 (L1 middlewares).

Cycle 53 design: logging не нужен headers modification, только
консольный output. Pure ASGI:
- Extract method/path из scope.
- Read body из scope['state']['body'] (cycle 52 pattern) если
  RequestBodyCache закешировал.
- Replay receive для log_response_body (cycle 44/52 pattern).
- logger.info/error вызываются как раньше.

ADR-0392 (волна 18, кластер G3 — логирование): middleware переведён на
канонический structlog-стек (``src.backend.core.logging.get_logger``).

* Раньше логгер брался через ``get_app_logger_provider()`` → legacy
  ``external_apis.logging_service.app_logger`` (``propagate=False`` +
  ``QueueHandler``): запись НЕ доходила до root-handler'а, вывод был
  plain-text (без JSON, ``correlation_id`` и PII-маскирования).
* Тела запроса/ответа писались НЕЗАМАСКИРОВАННЫМИ (в dev
  ``log_requests: true``) — утечка PII. Теперь тела проходят через
  канонический маскер ``core.security.pii_masker.default_masker``.
"""

from __future__ import annotations

from time import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.config.settings import settings
from src.backend.core.logging import get_logger
from src.backend.core.security.pii_masker import default_masker

__all__ = ("InnerRequestLoggingMiddleware",)


class InnerRequestLoggingMiddleware:
    """Pure ASGI middleware для логирования request/response (cycle 53).

    Поведение:
    - Логирует method/URL до call_next.
    - Логирует response status + duration после call_next.
    - Если log_body=True и method=POST: логирует body (cached or fresh).
    - Если log_body=True: логирует response body (collect chunks).

    Args:
        app: ASGI-приложение.

    """

    def __init__(self, app: ASGIApp) -> None:
        """Инициализация middleware.

        Args:
            app: ASGI-приложение.

        """
        # ADR-0392: structlog-стек вместо legacy ``app_logger`` —
        # запись доходит до root-handler'а и уходит в JSON-sinks.
        self.log_body = settings.logging.log_requests
        self.max_body_size = settings.logging.max_body_log_size
        self.logger = get_logger("entrypoints.middlewares.request_log")
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Обработка запроса и ответа с логированием.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        self.logger.info("http.request", method=method, path=path)

        start_time = time()

        # Capture body если нужно (cycle 53: cached body из state).
        if self.log_body and method == "POST":
            content_type = _get_header_value(scope, b"content-type") or ""
            if "multipart/form-data" not in content_type:
                await self._get_request_body(scope, receive)

        # Cycle 53 critical: response capture через send_wrapper
        # (для log_response_body если log_body=True).
        response_status: dict[str, int] = {"status": 0}
        response_chunks: list[bytes] = []
        response_complete: list[bool] = [False]

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message.get("status", 0)
            elif message["type"] == "http.response.body":
                if self.log_body:
                    response_chunks.append(message.get("body", b""))
                    # Прерываем после первого chunk (cycle 53 invariant:
                    # не accumulate весь stream body — только sample).
                    if not message.get("more_body", False):
                        response_complete[0] = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            self.logger.error(
                "http.request_failed",
                method=method,
                path=path,
                error=repr(exc),
                exc_info=True,
            )
            raise

        # Логирование тела ответа (если включено).
        if self.log_body and response_chunks:
            self._log_response_body_chunks(response_chunks, scope)

        # Логирование времени обработки запроса.
        process_time = (time() - start_time) * 1000
        self.logger.info(
            "http.response",
            status=response_status["status"],
            method=method,
            path=path,
            duration_ms=round(process_time, 2),
        )

    async def _get_request_body(self, scope: Scope, receive: Receive) -> bytes:
        """Получение и логирование тела запроса с ограничением по размеру.

        Cycle 53: использует cached body из state['body'] (если
        RequestBodyCacheMiddleware закешировал). Fallback на
        receive() loop.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.

        Returns:
            Тело запроса в bytes (или placeholder если > max_body_size).

        """
        # Cached body из state (cycle 52 RequestBodyCache pattern).
        state = scope.get("state", {}) if "state" in scope else {}
        cached = state.get("body") if isinstance(state, dict) else None
        if isinstance(cached, (bytes, bytearray)):
            body = bytes(cached)
        else:
            # Prod-fix 2026-09-09 (M6-#3): fallback-consume receive() здесь
            # отъедал тело у FastAPI-парсера (422 «Field required: body»,
            # запрос логировался, но endpoint получал пустой канал).
            # Канал receive() НЕ трогаем — body не логируется.
            self.logger.debug(
                "http.request_body_unavailable",
                reason="state['body'] отсутствует — body не логируется",
            )
            return "<body недоступен для логирования>".encode()

        if len(body) > self.max_body_size:
            self.logger.debug(
                "http.request_body_skipped",
                reason="тело запроса слишком велико для логирования",
                size=len(body),
                limit=self.max_body_size,
            )
            return "<тело запроса слишком велико для логирования>".encode()

        try:
            # ADR-0392: PII в теле запроса маскируется до записи в лог.
            self.logger.debug(
                "http.request_body", body=_mask_body(body.decode("utf-8"))
            )
        except UnicodeDecodeError:
            self.logger.warning(
                "http.request_body_not_utf8",
                reason="тело запроса содержит бинарные данные, логирование пропущено",
            )
        return body

    def _log_response_body_chunks(self, chunks: list[bytes], scope: Scope) -> None:
        """Логирование тела ответа из captured chunks (cycle 53 helper).

        Args:
            chunks: Captured body chunks from send_wrapper.
            scope: ASGI scope (для content-type detection).

        """
        from gzip import GzipFile
        from io import BytesIO

        body = b"".join(chunks)
        if not body:
            return

        content_encoding = _get_header_value(scope, b"content-encoding") or ""

        # Обработка сжатых данных (gzip).
        if content_encoding == "gzip":
            try:
                with GzipFile(fileobj=BytesIO(body)) as gzip_file:
                    body = gzip_file.read()
            except (OSError, EOFError) as gzip_exc:
                # cycle-9/D-AUDIT-994: narrow exceptions + observability.
                # OSError — gzip read failure, EOFError — truncated stream.
                # (zlib.error raised internally не экспортирован, OSError
                #  covers both gzip and underlying zlib errors.)
                self.logger.debug(
                    "http.response_body_gunzip_failed",
                    reason="не удалось распаковать gzip response body",
                    error=repr(gzip_exc),
                )

        if len(body) > self.max_body_size:
            body = "<тело ответа слишком велико для логирования>".encode()

        try:
            # ADR-0392: PII в теле ответа маскируется до записи в лог.
            self.logger.debug(
                "http.response_body",
                body=_mask_body(body.decode("utf-8")[: self.max_body_size]),
            )
        except UnicodeDecodeError:
            self.logger.debug("http.response_body_not_utf8")


def _mask_body(text: str) -> str:
    """Замаскировать PII в теле запроса/ответа перед записью в лог.

    Args:
        text: Текст тела (уже ограничен по размеру).

    Returns:
        Текст с замаскированными PII (email/phone/карты/токены и т.п.).

    """
    return default_masker().mask_text(text)


def _get_header_value(scope: Scope, name: bytes) -> str:
    """Извлекает header из ASGI scope по lowercase bytes-имени (cycle 43 helper)."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return ""
    return ""
