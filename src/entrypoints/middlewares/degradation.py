"""DegradationMiddleware (W26.5) — блокирует writes при degraded-инфраструктуре.

Если ``ResilienceCoordinator`` сообщает, что компонент ``db_main``
переключён на ``sqlite_ro`` (или другой read-only fallback), все
write-операции (POST/PUT/PATCH/DELETE) к API возвращают **HTTP 503
Service Unavailable** с заголовком ``Retry-After: <seconds>``.

Логика:
    * idempotent методы (GET/HEAD/OPTIONS) пропускаются всегда;
    * write-методы проверяют degradation_mode компонента ``db_main``;
    * 503 содержит JSON-payload ``{status: 'degraded', reason: ..., retry_after: ...}``.

Это страховка от потери данных: SQLite-RO snapshot не принимает writes
нативно (SQLite raises OperationalError), но без middleware ошибка
поднялась бы наверх с 5xx без явного указания причины.

Endpoints, которые safe для write в fallback-режиме (например, audit-
эмиссия в ClickHouse-fallback chain), исключаются через path-pattern
``DEGRADATION_BYPASS_PREFIXES``.
"""

from __future__ import annotations

import logging
from typing import Final

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

__all__ = ("DegradationMiddleware",)

logger = logging.getLogger(__name__)


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


class DegradationMiddleware(BaseHTTPMiddleware):
    """Блокирует write-методы, когда ``db_main`` работает в fallback-режиме."""

    def __init__(self, app: ASGIApp, *, retry_after: int = 30) -> None:
        super().__init__(app)
        self._retry_after = retry_after

    async def dispatch(self, request: Request, call_next):
        if request.method in _WRITE_METHODS and not self._is_bypassed(request.url.path):
            blocked = self._check_blocked_components()
            if blocked:
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "degraded",
                        "reason": (
                            "write blocked: components in fallback mode — "
                            f"{', '.join(blocked)}"
                        ),
                        "retry_after_seconds": self._retry_after,
                    },
                    headers={
                        "Retry-After": str(self._retry_after),
                        "X-Degradation-Mode": "write-blocked",
                    },
                )
        return await call_next(request)

    @staticmethod
    def _is_bypassed(path: str) -> bool:
        return any(path.startswith(prefix) for prefix in DEGRADATION_BYPASS_PREFIXES)

    @staticmethod
    def _check_blocked_components() -> list[str]:
        """Возвращает список компонентов, которые блокируют writes.

        Сейчас блокирует только ``db_main`` в fallback (sqlite_ro). Для
        других компонентов write-fallback допустим (cache-write, audit-
        write и т.п.).
        """
        try:
            from src.infrastructure.resilience.coordinator import (
                get_resilience_coordinator,
            )

            statuses = get_resilience_coordinator().status()
        except Exception:  # noqa: BLE001
            return []
        blocked: list[str] = []
        db = statuses.get("db_main")
        if db is not None and db.last_used_backend != "primary" and db.degradation in (
            "degraded",
            "down",
        ):
            blocked.append("db_main")
        return blocked
