"""Request timeout middleware с per-route override (S18 W6).

Поведение:
    * При ``per_route_timeout_enabled=False`` (default) — global timeout
      из ``settings.secure.request_timeout`` (legacy S0+ behaviour).
    * При flag=ON и наличии ``route_timeouts`` registry — longest-prefix
      match на ``request.url.path``. Match → используется ``total`` из
      registry. Miss → fallback на global default.

Источник registry (build at lifespan):
    Из :class:`RouteManifestV11.timeout` (``[timeout].total``) либо из
    DSL ``.policy.timeout(total=...)``. Wiring (RouteLoader →
    TimeoutMiddleware) — отдельная wave; сейчас registry опционален.
"""

import builtins
from asyncio import wait_for
from collections.abc import Mapping

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from src.backend.core.config.settings import settings
from src.backend.core.di.providers import get_app_logger_provider

__all__ = ("TimeoutMiddleware",)


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware для ограничения времени обработки запросов (S18 W6 extended).

    Args:
        app: ASGI приложение.
        route_timeouts: Опциональный registry ``{path_prefix: total_seconds}``.
            При наличии — middleware делает longest-prefix-match на
            ``request.url.path`` и применяет route-specific timeout.
            Miss → fallback на global default. Если ``None`` или ``{}``
            — middleware всегда использует global default.

    Notes:
        Feature-flag ``per_route_timeout_enabled`` (default-OFF) гейтит
        registry lookup. При OFF behaviour идентичен legacy S0+
        (single global timeout). Это обеспечивает безопасное
        развёртывание без риска регрессий.
    """

    def __init__(
        self, app: ASGIApp, *, route_timeouts: Mapping[str, float] | None = None
    ) -> None:
        super().__init__(app)
        # Сортируем по убыванию длины для longest-prefix-match.
        # Frozen tuple избегает мутаций после lifespan-bootstrap.
        items = tuple((p, float(t)) for p, t in (route_timeouts or {}).items())
        self._route_timeouts: tuple[tuple[str, float], ...] = tuple(
            sorted(items, key=lambda kv: len(kv[0]), reverse=True)
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Обрабатывает запрос с per-route или global timeout.

        Args:
            request: Входящий HTTP-запрос.
            call_next: Следующий middleware/обработчик.

        Returns:
            ``Response`` от downstream или ``JSONResponse(408)`` при тайм-ауте.
        """
        timeout_seconds = self._resolve_timeout(request.url.path)
        try:
            return await wait_for(call_next(request), timeout=timeout_seconds)
        except builtins.TimeoutError:
            get_app_logger_provider().warning(
                "Превышено время обработки запроса: %s (timeout=%.2fs)",
                request.url,
                timeout_seconds,
            )
            return JSONResponse(
                {"detail": "Превышено время обработки запроса"}, status_code=408
            )

    # ----------------------------------------------------------------- helpers

    def _resolve_timeout(self, path: str) -> float:
        """Возвращает timeout для ``path``: per-route или global fallback."""
        global_timeout = float(settings.secure.request_timeout)
        if not self._is_per_route_enabled() or not self._route_timeouts:
            return global_timeout
        for prefix, total in self._route_timeouts:
            if path.startswith(prefix):
                return total
        return global_timeout

    @staticmethod
    def _is_per_route_enabled() -> bool:
        """Lazy-проверка feature-flag ``per_route_timeout_enabled``."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(getattr(feature_flags, "per_route_timeout_enabled", False))
        except Exception as _:
            return False
