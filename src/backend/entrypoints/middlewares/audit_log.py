"""Расширенный аудит-лог: WHO / WHAT / WHERE / WHEN (cycle 48 pure ASGI).

Записывает в структурированном формате:
- WHO: client_id (из API key), IP-адрес
- WHAT: метод, путь, query params, payload hash
- WHERE: IP, User-Agent, Referer
- WHEN: timestamp, duration
- CORRELATION: request_id, correlation_id

Хранилища:
- Redis stream ``audit-log`` — для real-time поиска (TTL ограничен).
- ClickHouse ``audit_log`` — для долгосрочной аналитики и compliance.
- Graylog — для централизованного логирования.

Cycle 48: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-47 (L1 middlewares).

Cycle 48 critical: body buffering + body re-injection (аналог
cycle 44/45 pattern). Audit middleware читает body для
payload_hash, затем re-inject для downstream.
"""

import time as _time
from datetime import UTC, datetime

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.logging import get_logger
from src.backend.entrypoints.middlewares import _body_hash

__all__ = ("AuditLogMiddleware",)

_clickhouse_logger = get_logger("audit_log.clickhouse")


class AuditLogMiddleware:
    """Pure ASGI middleware: расширенный аудит-лог HTTP-запросов (cycle 48)."""

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
        """
        # Wave 6.5a: app_logger — через DI provider.
        from src.backend.core.di.providers import get_app_logger_provider

        self.app = app
        self.logger = get_app_logger_provider()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Аудитирует HTTP-запрос: WHO/WHAT/CORRELATION + fire-and-forget запись.

        Non-HTTP scope пробрасывается без audit.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = _time.monotonic()
        body_bytes: bytes = b""

        # IL-OBS1: сначала пробуем cached body из RequestBodyCacheMiddleware
        # (state['body']), затем graceful fallback на чтение receive() chunks.
        state = scope.get("state", {}) if "state" in scope else {}
        cached = state.get("body") if isinstance(state, dict) else None
        if isinstance(cached, (bytes, bytearray)):
            body_bytes = bytes(cached)
        else:
            # Pure ASGI: collect body chunks через receive().
            body_chunks: list[bytes] = []
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
                body_chunks.append(message.get("body", b""))
                more_body = message.get("more_body", False)
            body_bytes = b"".join(body_chunks)

        # Re-inject body для downstream handlers.
        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": body_bytes,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        # Capture response status для audit.
        response_status: dict[str, int] = {"status": 0}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message.get("status", 0)
            await send(message)

        # Пробрасываем downstream с body replay.
        await self.app(scope, replay_receive, send_wrapper)

        duration_ms = (_time.monotonic() - start) * 1000

        # Извлекаем audit event data (cycle 48: из ASGI scope, не из Request).
        # WHO
        auth = state.get("auth") if isinstance(state, dict) else None
        client_id = getattr(auth, "principal", None) or "anonymous"
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        # WHERE: user-agent (case-insensitive).
        user_agent = ""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"user-agent":
                try:
                    user_agent = header_value.decode("latin-1")[:200]
                except UnicodeDecodeError:
                    pass
                break

        # WHAT
        payload_hash = ""
        if body_bytes:
            payload_hash = _body_hash.payload_hash(body_bytes, prefix_len=16)

        # CORRELATION
        request_id = (
            state.get("request_id", "n/a") if isinstance(state, dict) else "n/a"
        )
        correlation_id = (
            state.get("correlation_id", "n/a") if isinstance(state, dict) else "n/a"
        )

        audit_event = {
            "type": "audit",
            "method": scope.get("method", ""),
            "path": scope.get("path", ""),
            "query": scope.get("query_string", b"").decode(
                "latin-1", errors="replace"
            ),
            "status": response_status["status"],
            "duration_ms": round(duration_ms, 1),
            "client_id": client_id,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "payload_hash": payload_hash,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "timestamp": _time.time(),
            "ts_iso": datetime.now(UTC).isoformat(),
        }

        # Fire-and-forget: ошибки записи НЕ прерывают request.
        try:
            self.logger.info("audit_event", extra=audit_event)
        except Exception as exc:
            _clickhouse_logger.warning("Audit emit failed: %s", exc)

        # Также ClickHouse writer (lazy import).
        try:
            from src.backend.core.di.providers import (
                get_audit_log_writer_provider,
            )

            writer = get_audit_log_writer_provider()
            if writer is not None:
                # Async write — но мы в sync path, используем create_task.
                import asyncio

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(writer.write(audit_event))
        except Exception as exc:
            _clickhouse_logger.debug("ClickHouse audit write skipped: %s", exc)

    @staticmethod
    async def _send_response(send: Send, status: int, body: dict) -> None:
        """Helper: отправляет response через send."""
        import json

        body_bytes = json.dumps(body).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})
