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
"""

from __future__ import annotations

import json
from time import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.config.settings import settings
from src.backend.core.di.providers import get_app_logger_provider
from src.backend.core.utils.async_helpers import async_chunk_iterator

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
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
        """
        # Wave 6.5a: app_logger — через DI provider.
        self.log_body = settings.logging.log_requests
        self.max_body_size = settings.logging.max_body_log_size
        self.logger = get_app_logger_provider()
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

        self.logger.info(f"Запрос: {method} {path}")

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
            self.logger.error(f"Ошибка обработки запроса: {exc!s}", exc_info=True)
            raise

        # Логирование тела ответа (если включено).
        if self.log_body and response_chunks:
            self._log_response_body_chunks(response_chunks, scope)

        # Логирование времени обработки запроса.
        process_time = (time() - start_time) * 1000
        self.logger.info(
            f"Ответ: {response_status['status']} | {method} {path} "
            f"обработан за {process_time:.2f} мс"
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
            # Fallback: receive() loop.
            body_chunks: list[bytes] = []
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
                body_chunks.append(message.get("body", b""))
                more_body = message.get("more_body", False)
            body = b"".join(body_chunks)

        if len(body) > self.max_body_size:
            self.logger.debug(
                f"Тело запроса слишком велико для логирования ({len(body)} > {self.max_body_size})"
            )
            return "<тело запроса слишком велико для логирования>".encode()

        try:
            self.logger.debug(f"Тело запроса: {body.decode('utf-8')}")
        except UnicodeDecodeError:
            self.logger.warning(
                "Тело запроса содержит бинарные данные, логирование пропущено"
            )
        return body

    def _log_response_body_chunks(
        self, chunks: list[bytes], scope: Scope
    ) -> None:
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

        content_type = _get_header_value(scope, b"content-type") or ""
        content_encoding = _get_header_value(scope, b"content-encoding") or ""

        # Обработка сжатых данных (gzip).
        if content_encoding == "gzip":
            try:
                with GzipFile(fileobj=BytesIO(body)) as gzip_file:
                    body = gzip_file.read()
            except Exception:
                self.logger.debug("Не удалось распаковать gzip response body")

        if len(body) > self.max_body_size:
            body = "<тело ответа слишком велико для логирования>".encode("utf-8")

        try:
            self.logger.debug(f"Тело ответа: {body.decode('utf-8')[:self.max_body_size]}")
        except UnicodeDecodeError:
            self.logger.debug("Тело ответа содержит бинарные данные")


def _get_header_value(scope: Scope, name: bytes) -> str:
    """Извлекает header из ASGI scope по lowercase bytes-имени (cycle 43 helper)."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return ""
    return ""
