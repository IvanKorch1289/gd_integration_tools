"""Audit Replay Middleware — record request/response в Redis stream (cycle 45 pure ASGI).

Используется для:
- Debug production incidents (re-run historical requests)
- Compliance audit trails
- Replay testing после refactoring

Multi-instance safe: все данные пишутся в Redis (centralized storage).

Storage: Redis stream "audit:requests" с TTL retention.
Replay UI: Streamlit page (планируется).

Cycle 45: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-44 (L1 middlewares).

Cycle 45 critical: body buffering + body re-injection.
Audit middleware должен:
1. Прочитать body (через receive() chunks в pure ASGI).
2. Передать downstream (handler может читать body повторно).
3. Записать request + response в Redis stream.

В BaseHTTPMiddleware body уже buffered. В pure ASGI:
- collect body chunks в middleware
- re-inject body через replay_receive для downstream
"""

from __future__ import annotations

import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.logging import get_logger

__all__ = ("AuditReplayMiddleware",)

logger = get_logger("infra.audit_replay")

_STREAM_NAME = "audit:requests"
_MAX_BODY_SIZE = 8192  # truncate bodies > 8KB


class AuditReplayMiddleware:
    """Pure ASGI middleware: запись request/response в Redis stream (cycle 45).

    Args:
        skip_paths: Paths to exclude from audit (e.g., /health, /metrics).
        sample_rate: Доля запросов для аудита (0.0..1.0). 1.0 = все запросы.

    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        skip_paths: set[str] | None = None,
        sample_rate: float = 1.0,
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            skip_paths: Paths to exclude from audit.
            sample_rate: Доля запросов для аудита (0.0..1.0).

        """
        self.app = app
        self._skip_paths = skip_paths or {"/health", "/metrics", "/readyz", "/livez"}
        self._sample_rate = max(0.0, min(1.0, sample_rate))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope пробрасывается без audit.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Skip paths (health-like) — без audit.
        if path in self._skip_paths:
            await self.app(scope, receive, send)
            return

        # Sampling — пропускаем часть запросов.
        if self._sample_rate < 1.0:
            import random

            if random.random() > self._sample_rate:
                await self.app(scope, receive, send)
                return

        start = time.monotonic()

        # IL-OBS1: сначала cached body (set via RequestBodyCacheMiddleware),
        # затем fallback на receive() chunks.
        request_body_bytes = b""
        cached = scope.get("state", {}).get("body") if "state" in scope else None
        if isinstance(cached, (bytes, bytearray)):
            request_body_bytes = bytes(cached)
        else:
            # Pure ASGI: collect body chunks через receive().
            request_body_bytes = await self._collect_body(receive)

        # Re-inject body для downstream через replay_receive closure.
        body_sent = False

        async def replay_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": request_body_bytes,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        # Capture response для audit record.
        response_status: dict[str, int] = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message.get("status", 0)
            await send(message)

        # Пробрасываем downstream с body replay.
        await self.app(scope, replay_receive, send_wrapper)

        duration_ms = round((time.monotonic() - start) * 1000, 2)

        # Async audit record (non-blocking — exceptions НЕ пробрасываются).
        try:
            await self._audit(
                scope, request_body_bytes, response_status["status"], duration_ms,
            )
        except Exception as exc:
            logger.warning("Audit record failed: %s", exc)

    @staticmethod
    async def _collect_body(receive: Receive) -> bytes:
        """Collect body chunks через receive() (cycle 45 helper)."""
        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            body_chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        return b"".join(body_chunks)

    async def _audit(
        self,
        scope: Scope,
        request_body: bytes,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """Отправляет запись в Redis stream (cycle 45 helper)."""
        try:
            from src.backend.core.di.providers import get_redis_stream_client_provider

            redis_client = get_redis_stream_client_provider()
        except ImportError:
            return

        # Extract client IP + correlation_id из ASGI scope (no-Request).
        client = scope.get("client")
        client_ip = client[0] if client else ""

        # Read correlation_id из headers (case-insensitive).
        correlation_id = ""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"x-correlation-id":
                try:
                    correlation_id = header_value.decode("latin-1")
                except UnicodeDecodeError:
                    pass
                break

        entry = {
            "timestamp": time.time(),
            "method": scope.get("method", ""),
            "path": scope.get("path", ""),
            "query": scope.get("query_string", b"").decode("latin-1", errors="replace"),
            "client_ip": client_ip,
            "correlation_id": correlation_id,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "request_body": request_body[:_MAX_BODY_SIZE].decode(
                "utf-8", errors="replace",
            ),
        }

        try:
            await redis_client.add_to_stream(stream_name=_STREAM_NAME, data=entry)
        except (ConnectionError, TimeoutError, AttributeError) as exc:
            logger.debug("Redis audit stream unavailable: %s", exc)


async def list_audit_records(
    *, count: int = 100, start_id: str = "-",
) -> list[dict[str, Any]]:
    """Читает последние записи из audit stream для Replay UI."""
    try:
        from src.backend.core.di.providers import get_redis_stream_client_provider

        redis_client = get_redis_stream_client_provider()
        records = await redis_client.read_stream(
            stream_name=_STREAM_NAME, count=count, start_id=start_id,
        )
        return records or []
    except Exception as exc:
        logger.warning("Failed to read audit stream: %s", exc)
        return []


async def replay_audit_record(record_id: str) -> dict[str, Any]:
    """Выполняет повтор запроса по ID для дебага.

    Возвращает {"status": "replayed", "record_id": ..., "new_response": {...}}.
    """
    try:
        from src.backend.core.di.providers import get_redis_stream_client_provider

        redis_client = get_redis_stream_client_provider()
        records = await redis_client.read_stream(
            stream_name=_STREAM_NAME, count=1, start_id=record_id,
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    if not records:
        return {"status": "error", "error": f"Record {record_id} not found"}

    record = records[0]
    return {
        "status": "ready_for_replay",
        "record_id": record_id,
        "method": record.get("method"),
        "path": record.get("path"),
        "body": record.get("request_body", ""),
    }
