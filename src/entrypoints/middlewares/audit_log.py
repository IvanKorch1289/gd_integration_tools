"""Расширенный аудит-лог: WHO / WHAT / WHERE / WHEN.

Записывает в структурированном формате:
- WHO: client_id (из API key), IP-адрес
- WHAT: метод, путь, query params, payload hash
- WHERE: IP, User-Agent, Referer
- WHEN: timestamp, duration
- CORRELATION: request_id, correlation_id

Аудит-события сохраняются в Redis stream для поиска
и в Graylog для долговременного хранения.
"""

import hashlib
import time as _time

import orjson
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

__all__ = ("AuditLogMiddleware",)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Расширенный аудит-лог HTTP-запросов."""

    def __init__(self, app: ASGIApp) -> None:
        from app.infrastructure.external_apis.logging_service import app_logger

        super().__init__(app)
        self.logger = app_logger

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = _time.monotonic()
        body_bytes: bytes = b""

        try:
            body_bytes = await request.body()
        except Exception:
            pass

        response = await call_next(request)
        duration_ms = (_time.monotonic() - start) * 1000

        # WHO
        client_id = getattr(request.state, "client_id", None) or "anonymous"
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "")[:200]

        # WHAT
        payload_hash = ""
        if body_bytes:
            payload_hash = hashlib.sha256(body_bytes).hexdigest()[:16]

        # CORRELATION
        request_id = getattr(request.state, "request_id", "n/a")
        correlation_id = getattr(request.state, "correlation_id", "n/a")

        audit_event = {
            "type": "audit",
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query) if request.url.query else "",
            "status": response.status_code,
            "duration_ms": round(duration_ms, 1),
            "client_id": client_id,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "payload_hash": payload_hash,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "timestamp": _time.time(),
        }

        self.logger.info(
            "AUDIT | %s %s | status=%d | %.1fms | client=%s | ip=%s | corr=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            client_id,
            client_ip,
            correlation_id,
        )

        # Асинхронная запись в Redis stream (fire-and-forget)
        try:
            from app.infrastructure.clients.storage.redis import redis_client

            await redis_client.add_to_stream(
                stream_name="audit-log",
                data={k: str(v) for k, v in audit_event.items()},
            )
        except Exception:
            pass

        return response
