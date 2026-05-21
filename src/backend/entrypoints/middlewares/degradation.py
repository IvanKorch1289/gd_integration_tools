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


class DegradationMiddleware(BaseHTTPMiddleware):
    """Блокирует операции согласно :class:`DegradationMode` (S13 K2 W4).

    Уровни:

    * ``FULL`` — всё разрешено.
    * ``DEGRADED``/``READ_ONLY`` — блок POST/PATCH/DELETE на ``/api/v1/*``.
    * ``CACHE_ONLY`` — то же + force ``cache_first=true`` header в downstream.
    * ``EMERGENCY``/``ESSENTIAL_ONLY`` — только tech/health/metrics endpoints.
    * ``MAINTENANCE`` — только liveness + degradation switch.
    """

    def __init__(self, app: ASGIApp, *, retry_after: int = 30) -> None:
        super().__init__(app)
        self._retry_after = retry_after

    async def dispatch(self, request: Request, call_next):
        from src.backend.core.resilience.degradation import (
            DegradationMode,
            degradation_manager,
            mode_at_least,
        )

        path = request.url.path
        method = request.method
        mode = degradation_manager.current_mode

        # MAINTENANCE: всё кроме liveness + degradation switch.
        if mode_at_least(mode, DegradationMode.MAINTENANCE):
            if not any(path.startswith(p) for p in _MAINTENANCE_PATH_PREFIXES):
                return self._build_503(
                    f"system in {mode.value} mode", header="maintenance"
                )

        # ESSENTIAL_ONLY/EMERGENCY: всё кроме health/tech/metrics.
        if mode_at_least(mode, DegradationMode.ESSENTIAL_ONLY):
            if not any(path.startswith(p) for p in _ESSENTIAL_PATH_PREFIXES):
                return self._build_503(
                    f"only essential endpoints available ({mode.value})",
                    header="essential-only",
                )

        # CACHE_ONLY: writes блокируем, GET force cache_first.
        if mode_at_least(mode, DegradationMode.CACHE_ONLY):
            if method in _WRITE_METHODS and not self._is_bypassed(path):
                return self._build_503(
                    f"writes blocked: {mode.value}", header="cache-only-no-writes"
                )

        # READ_ONLY/DEGRADED: блок writes.
        if mode_at_least(mode, DegradationMode.READ_ONLY):
            if method in _WRITE_METHODS and not self._is_bypassed(path):
                return self._build_503(
                    f"writes blocked: system in {mode.value} mode", header="read-only"
                )

        # Legacy: db_main fallback → блок writes.
        if method in _WRITE_METHODS and not self._is_bypassed(path):
            blocked = self._check_blocked_components()
            if blocked:
                return self._build_503(
                    f"write blocked: components in fallback mode — {', '.join(blocked)}",
                    header="write-blocked",
                )

        response = await call_next(request)
        if mode_at_least(mode, DegradationMode.CACHE_ONLY):
            response.headers["X-Degradation-Mode"] = mode.value
        return response

    def _build_503(self, reason: str, *, header: str) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "reason": reason,
                "retry_after_seconds": self._retry_after,
            },
            headers={
                "Retry-After": str(self._retry_after),
                "X-Degradation-Mode": header,
            },
        )

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
        # Wave 6.5a: ResilienceCoordinator — через DI provider.
        try:
            from src.backend.core.di.providers import (
                get_resilience_coordinator_provider,
            )

            statuses = get_resilience_coordinator_provider().status()
        except Exception:  # noqa: BLE001
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
