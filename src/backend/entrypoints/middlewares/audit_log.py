"""Расширенный аудит-лог: WHO / WHAT / WHERE / WHEN.

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
"""

import hashlib
import logging
import time as _time
from datetime import UTC, datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

__all__ = ("AuditLogMiddleware",)

_clickhouse_logger = logging.getLogger("audit_log.clickhouse")


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Расширенный аудит-лог HTTP-запросов."""

    def __init__(self, app: ASGIApp) -> None:
        # Wave 6.5a: app_logger — через DI provider (lazy resolve в __init__,
        # т.к. logger глобальный singleton, доступен сразу при импорте).
        from src.backend.core.di.providers import get_app_logger_provider

        super().__init__(app)
        self.logger = get_app_logger_provider()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = _time.monotonic()
        body_bytes: bytes = b""

        # IL-OBS1: сначала пробуем cached body из RequestBodyCacheMiddleware,
        # затем graceful fallback на чтение потока.
        cached = getattr(request.state, "body", None)
        if isinstance(cached, (bytes, bytearray)):
            body_bytes = bytes(cached)
        else:
            try:
                body_bytes = await request.body()
            except Exception:  # noqa: BLE001, S110
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

        # Асинхронная запись в Redis stream (fire-and-forget).
        # Wave 6.5a: redis_client — через DI provider.
        try:
            from src.backend.core.di.providers import get_redis_stream_client_provider

            redis_client = get_redis_stream_client_provider()
            await redis_client.add_to_stream(
                stream_name="audit-log",
                data={k: str(v) for k, v in audit_event.items()},
            )
        except Exception:  # noqa: BLE001, S110
            pass

        # Запись в ClickHouse для долгосрочной аналитики (fire-and-forget).
        # Wave 6.5a: clickhouse_client — через DI provider.
        try:
            from src.backend.core.di.providers import get_clickhouse_client_provider

            ch_row = {
                "ts": datetime.fromtimestamp(
                    audit_event["timestamp"], tz=UTC
                ).isoformat(),
                "method": audit_event["method"],
                "path": audit_event["path"],
                "query": audit_event["query"],
                "status": int(audit_event["status"]),
                "duration_ms": float(audit_event["duration_ms"]),
                "client_id": audit_event["client_id"],
                "client_ip": audit_event["client_ip"],
                "user_agent": audit_event["user_agent"],
                "payload_hash": audit_event["payload_hash"],
                "request_id": audit_event["request_id"],
                "correlation_id": audit_event["correlation_id"],
            }
            ch = get_clickhouse_client_provider()
            await ch.insert("audit_log", [ch_row])
        except Exception as exc:  # noqa: BLE001
            _clickhouse_logger.debug("ClickHouse audit insert failed: %s", exc)

        return response
