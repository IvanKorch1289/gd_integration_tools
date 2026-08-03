"""DegradationMiddleware (W26.5) — блокирует writes при degraded-инфраструктуре (cycle 42 pure ASGI).

Если ``ResilienceCoordinator`` сообщает, что компонент ``db_main``
переключён на ``sqlite_ro`` (или другой read-only fallback), все
write-операции (POST/PUT/PATCH/DELETE) к API возвращают **HTTP 503
Service Unavailable** с заголовком ``Retry-After: <seconds>``.

Логика:
    * idempotent методы (GET/HEAD/OPTIONS) пропускаются всегда;
    * write-методы проверяют degradation_mode компонента ``db_main``;
    * 503 содержит JSON-payload ``{status: 'degraded', reason: ..., retry_after: ...}``.

Cycle 42: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-41 (L1 middlewares).

Cycle 42 critical: как и cycle 39-41, pure ASGI не может raise
для response. 503 отправляется через send напрямую.
"""

from __future__ import annotations

import json
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.logging import get_logger

__all__ = ("DegradationMiddleware",)

logger = get_logger(__name__)


_WRITE_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Path-prefix'ы, не блокирующиеся в fallback-режиме (health, metrics, audit и т.п.).
DEGRADATION_BYPASS_PREFIXES: Final[tuple[str, ...]] = (
    "/health",
    "/liveness",
    "/readiness",
    "/startup",
    "/components",
    "/metrics",
    "/api/v1/audit",  # audit-events — обязаны проходить даже при degraded
)

_ESSENTIAL_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "/health",
    "/liveness",
    "/readiness",
    "/startup",
    "/components",
    "/metrics",
    "/tech/degradation",
    "/api/v1/tech/degradation",
)

_MAINTENANCE_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "/health/liveness",
    "/tech/degradation",
    "/api/v1/tech/degradation",
)


def _build_503_json(
    reason: str, retry_after: int, header: str
) -> tuple[bytes, list[tuple[bytes, bytes]]]:
    """Создаёт 503 JSON body + headers (cycle 42 helper).

    Pure ASGI: возвращает bytes + headers для отправки через send.
    """
    body = json.dumps(
        {
            "status": "degraded",
            "reason": reason,
            "retry_after_seconds": retry_after,
        }
    ).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("latin-1")),
        (b"retry-after", str(retry_after).encode("latin-1")),
        (b"x-degradation-mode", header.encode("latin-1")),
    ]
    return body, headers


class DegradationMiddleware:
    """Pure ASGI middleware: блокирует writes в degraded-режиме (S13 K2 W4).

    Cycle 42 design:
    - Mode check в __call__ (читает scope['path'] и scope['method']).
    - Restrictive mode → отправляет 503 через send (no-raise, cycle 39).
    - Allowed path → оборачивает send чтобы инжектить X-Degradation-Mode
      header в response (CACHE_ONLY mode).

    Public API сохранён: ``DegradationMiddleware(app, retry_after=30)``.
    """

    def __init__(self, app: ASGIApp, *, retry_after: int = 30) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            retry_after: TTL для Retry-After header (в секундах).
        """
        self.app = app
        self._retry_after = retry_after

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope пробрасывается downstream без degradation check.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Lazy import — degradation_manager может быть тяжёлым
        # (DI dependencies), не грузим при импорте модуля.
        from src.backend.core.resilience.degradation import (
            DegradationMode,
            degradation_manager,
            mode_at_least,
        )

        path = scope.get("path", "")
        method = scope.get("method", "")
        mode = degradation_manager.current_mode

        # MAINTENANCE: всё кроме liveness + degradation switch.
        if mode_at_least(mode, DegradationMode.MAINTENANCE):
            if not any(path.startswith(p) for p in _MAINTENANCE_PATH_PREFIXES):
                await self._send_503(
                    send,
                    reason=f"system in {mode.value} mode",
                    header="maintenance",
                )
                return

        # ESSENTIAL_ONLY/EMERGENCY: всё кроме health/tech/metrics.
        if mode_at_least(mode, DegradationMode.ESSENTIAL_ONLY):
            if not any(path.startswith(p) for p in _ESSENTIAL_PATH_PREFIXES):
                await self._send_503(
                    send,
                    reason=f"only essential endpoints available ({mode.value})",
                    header="essential-only",
                )
                return

        # CACHE_ONLY: блок writes (проверяется ПЕРВЫМ — CACHE_ONLY > READ_ONLY
        # в mode_at_least, поэтому CACHE_ONLY ловит и READ_ONLY, но
        # возвращает более специфичный header).
        if mode_at_least(mode, DegradationMode.CACHE_ONLY):
            if method in _WRITE_METHODS and not self._is_bypassed(path):
                await self._send_503(
                    send,
                    reason=f"writes blocked: {mode.value}",
                    header="cache-only-no-writes",
                )
                return

        # READ_ONLY: блок writes.
        if mode_at_least(mode, DegradationMode.READ_ONLY):
            if method in _WRITE_METHODS and not self._is_bypassed(path):
                await self._send_503(
                    send,
                    reason=f"writes blocked: system in {mode.value} mode",
                    header="read-only",
                )
                return

        # Legacy: db_main fallback → блок writes.
        if method in _WRITE_METHODS and not self._is_bypassed(path):
            blocked = self._check_blocked_components()
            if blocked:
                await self._send_503(
                    send,
                    reason=f"write blocked: components in fallback mode — {', '.join(blocked)}",
                    header="write-blocked",
                )
                return

        # Allowed → пробрасываем downstream.
        # Если mode CACHE_ONLY+ → инжектим X-Degradation-Mode header
        # через send-wrapper (чтобы downstream видел cache_first=true).
        if mode_at_least(mode, DegradationMode.CACHE_ONLY):
            send_wrapper = self._make_mode_header_wrapper(send, mode.value)
            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)

    @staticmethod
    def _is_bypassed(path: str) -> bool:
        return any(path.startswith(prefix) for prefix in DEGRADATION_BYPASS_PREFIXES)

    @staticmethod
    def _check_blocked_components() -> list[str]:
        """Возвращает список компонентов, которые блокируют writes."""
        try:
            from src.backend.core.di.providers import (
                get_resilience_coordinator_provider,
            )

            statuses = get_resilience_coordinator_provider().status()
        except Exception:
            return []
        blocked: list[str] = []
        db = statuses.get("db_main")
        if (
            db is not None
            and db.last_used_backend != "primary"
            and db.degradation in ("degraded", "down")
        ):
            blocked.append("db_main")
        return blocked

    async def _send_503(
        self, send: Send, *, reason: str, header: str
    ) -> None:
        """503 sender (instance method, использует self._retry_after).

        Cycle 42: instance method (не static) — нужен self._retry_after.
        Pure ASGI: 503 отправляется через send явно (no-raise, cycle 39).
        """
        body, headers = _build_503_json(reason, self._retry_after, header)
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _make_mode_header_wrapper(send: Send, mode_value: str) -> Send:
        """Создаёт send-wrapper который инжектит X-Degradation-Mode header.

        Cycle 42 pattern: send-wrapper для добавления response header
        (как cycle 36 RequestID, cycle 37 AuthMethodHeader).
        """

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                existing = [
                    (k, v) for k, v in existing
                    if k.lower() != b"x-degradation-mode"
                ]
                existing.append(
                    (b"x-degradation-mode", mode_value.encode("latin-1"))
                )
                message["headers"] = existing
            await send(message)

        return send_wrapper
