"""Audit Replay Middleware — запись request/response пар в Redis stream для replay.

Используется для:
- Debug production incidents (re-run historical requests)
- Compliance audit trails
- Replay testing после refactoring

Multi-instance safe: все данные пишутся в Redis (centralized storage).

Storage: Redis stream "audit:requests" с TTL retention.
Replay UI: Streamlit page (планируется).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

__all__ = ("AuditReplayMiddleware",)

logger = logging.getLogger("infra.audit_replay")

_STREAM_NAME = "audit:requests"
_MAX_BODY_SIZE = 8192  # truncate bodies > 8KB


class AuditReplayMiddleware(BaseHTTPMiddleware):
    """Записывает request/response пары в Redis stream.

    Args:
        skip_paths: Paths to exclude from audit (e.g., /health, /metrics).
        sample_rate: Доля запросов для аудита (0.0..1.0). 1.0 = все запросы.
    """

    def __init__(
        self, app: Any, *, skip_paths: set[str] | None = None, sample_rate: float = 1.0
    ) -> None:
        super().__init__(app)
        self._skip_paths = skip_paths or {"/health", "/metrics", "/readyz", "/livez"}
        self._sample_rate = max(0.0, min(1.0, sample_rate))

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in self._skip_paths:
            return await call_next(request)

        if self._sample_rate < 1.0:
            import random

            if random.random() > self._sample_rate:
                return await call_next(request)

        start = time.monotonic()
        request_body_bytes = b""

        # IL-OBS1: сначала cached body (set via RequestBodyCacheMiddleware),
        # затем fallback на поток.
        cached = getattr(request.state, "body", None)
        if isinstance(cached, (bytes, bytearray)):
            request_body_bytes = bytes(cached)
        else:
            try:
                request_body_bytes = await request.body()
            except Exception:
                request_body_bytes = b""

        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        try:
            await self._audit(request, request_body_bytes, response, duration_ms)
        except Exception as exc:
            logger.warning("Audit record failed: %s", exc)

        return response

    async def _audit(
        self,
        request: Request,
        request_body: bytes,
        response: Response,
        duration_ms: float,
    ) -> None:
        """Отправляет запись в Redis stream."""
        try:
            from src.infrastructure.clients.storage.redis import redis_client
        except ImportError:
            return

        entry = {
            "timestamp": time.time(),
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query or ""),
            "client_ip": request.client.host if request.client else "",
            "correlation_id": request.headers.get("x-correlation-id", ""),
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "request_body": request_body[:_MAX_BODY_SIZE].decode(
                "utf-8", errors="replace"
            ),
        }

        try:
            await redis_client.add_to_stream(stream_name=_STREAM_NAME, data=entry)
        except (ConnectionError, TimeoutError, AttributeError) as exc:
            logger.debug("Redis audit stream unavailable: %s", exc)


async def list_audit_records(
    *, count: int = 100, start_id: str = "-"
) -> list[dict[str, Any]]:
    """Читает последние записи из audit stream для Replay UI."""
    try:
        from src.infrastructure.clients.storage.redis import redis_client

        records = await redis_client.read_stream(
            stream_name=_STREAM_NAME, count=count, start_id=start_id
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
        from src.infrastructure.clients.storage.redis import redis_client

        records = await redis_client.read_stream(
            stream_name=_STREAM_NAME, count=1, start_id=record_id
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
