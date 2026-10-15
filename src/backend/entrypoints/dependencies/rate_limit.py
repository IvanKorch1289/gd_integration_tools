"""Rate-limit зависимость для FastAPI-роутов.

В ``fastapi-limiter==0.2.0`` backend — ``RedisLimiterAdapter`` (multi-instance safe),
``FastAPILimiter.init`` упразднён. Лимит применяется per-route через
``Depends(get_default_rate_limiter())``. Identifier и callback — общие из
``core.decorators.limiting_callbacks``.

S168 W11 P1-3: миграция с ``pyrate_limiter.Limiter`` (in-memory, per-process)
на ``unified_rate_limiter.RedisRateLimiter`` (multi-instance via Redis).
Ponytail minimum: ``RedisLimiterAdapter`` реализует только ``try_acquire_async``
для совместимости с ``fastapi_limiter.depends.RateLimiter``. ``get_rate_limiter``
fail-open при недоступности Redis (как в ``webhook/handler.py``).

2026-10-15 fix (re-audit): ``fastapi_limiter==0.2.0`` upstream имеет bug —
``RateLimiter.__call__`` обращается к ``route.path`` без проверки типа,
что падает с ``AttributeError`` для ``_IncludedRouter`` (sub-routers,
используемые для nested APIRouter). В этом проекте это сломало
``/api/v1/invocations`` (5xx internal error). Workaround: subclass
:class:`SafeRateLimiter` который использует ``getattr(route, 'path', ...)``
и работает и для APIRoute, и для _IncludedRouter.

Расположение в ``entrypoints/dependencies/`` отражает суть API:
это ``Depends``-объект, не ASGI-middleware. Sprint 1 V16 cleanup
перенёс файл из ``entrypoints/middlewares/``.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi_limiter.depends import RateLimiter as RateLimitDependency
from fastapi_limiter.depends import RateLimiter as _UpstreamRateLimiter
from fastapi_limiter.depends import WebSocketRateLimiter
from starlette.requests import Request
from starlette.responses import Response

from src.backend.core.config.security import secure_settings
from src.backend.core.decorators.limiting_callbacks import (
    default_callback,
    default_identifier,
)
from src.backend.services.resilience.rate_limiter import (
    RateLimit,
    RateLimitExceeded,
    get_rate_limiter,
)

__all__ = (
    "RateLimitDependency",
    "RedisLimiterAdapter",
    "SafeRateLimiter",
    "WebSocketRateLimiter",
    "get_default_limiter",
    "get_default_rate_limiter",
)


class RedisLimiterAdapter:
    """Adapter: ``pyrate_limiter.Limiter`` interface → ``RedisRateLimiter`` backend.

    Multi-instance safe via Redis (atomic INCR/EXPIRE). Совместим с
    ``fastapi_limiter.depends.RateLimiter``, который вызывает только
    ``limiter.try_acquire_async(key, blocking=...)``.

    Args:
        rate_limit: Maximum permits per window.
        window_seconds: Window duration in seconds.

    """

    def __init__(self, *, rate_limit: int, window_seconds: int) -> None:
        """Инициализирует middleware."""
        self._limiter = get_rate_limiter()
        self._rate_limit = rate_limit
        self._window_seconds = window_seconds

    async def try_acquire_async(
        self,
        name: str = "pyrate",
        weight: int = 1,
        blocking: bool = False,
        timeout: int | float = -1,
    ) -> bool:
        """Acquire `weight` permits из bucket `name`. Multi-instance через Redis.

        Сигнатура обязана совпадать с ``pyrate_limiter.Limiter.try_acquire_async``
        (``name``, ``weight``, ``blocking``, ``timeout``) — именно так её
        вызывает ``RateLimiter.__call__`` upstream и наш :class:`SafeRateLimiter`.
        2026-10-15 fix: параметр ``blocking`` отсутствовал → ``TypeError`` →
        500 ``internal_error`` на каждом rate-limited endpoint.

        ``blocking`` принимается для совместимости с протоколом, но ожидание
        permit'а **не реализовано**: Redis-адаптер проверяет лимит один раз и
        сразу возвращает ``False`` при превышении (проект работает с
        ``blocking=False`` → мгновенный 429 через callback).

        Returns:
            True if permits acquired, False if rate limit exceeded.

        """
        del blocking  # protocol-compat; поведение описано в docstring
        # Map pyrate_limiter semantics → RedisRateLimiter.check()
        # window: timeout > 0 используем timeout, иначе configured window
        if timeout is None or timeout < 0:
            window = self._window_seconds
        else:
            window = max(1, int(timeout))
        try:
            await self._limiter.check(
                name,
                RateLimit(limit=weight, window_seconds=window, key_prefix="pyrate"),
            )
        except RateLimitExceeded:
            return False
        return True

    @property
    def rate_limit(self) -> int:
        """Configured rate limit (permits per window)."""
        return self._rate_limit

    @property
    def window_seconds(self) -> int:
        """Configured window in seconds."""
        return self._window_seconds


class SafeRateLimiter(_UpstreamRateLimiter):
    """Subclass upstream ``fastapi_limiter.depends.RateLimiter`` с fix для
    ``_IncludedRouter.path`` AttributeError.

    2026-10-15 fix: upstream ``RateLimiter.__call__`` (lines 30-34) делает::

        for i, route in enumerate(request.app.routes):
            if (
                route.path == request.scope["path"]  # <-- bug: _IncludedRouter has no .path
                and hasattr(route, "methods")
                and request.method in route.methods
            ):

    В FastAPI>=0.100 ``request.app.routes`` содержит как ``APIRoute`` (имеет
    ``.path``), так и ``_IncludedRouter`` (sub-router, ``.prefix`` + ``.routes``,
    БЕЗ ``.path``). При первой итерации по sub-router'у upstream
    роняет ``AttributeError`` → 500 internal error.

    Fix: используем ``getattr(route, "path", ...)`` для APIRoute,
    и ``getattr(route, "prefix", "")`` для _IncludedRouter. Это
    совместимо с upstream контрактом (rate limit key остаётся
    route_index-based, не path-based — dependency-isolation
    через ``self is dependency.dependency`` сохраняется).

    Дополнительно: добавлен ``getattr(route, "methods", None)``
    чтобы не падать на роутах без HTTP methods (например, lifespan
    routes, mount-точки).

    Минимально-совместимое исправление, не форкаем библиотеку
    полностью — только ``__call__`` override.
    """

    async def __call__(  # type: ignore[override]
        self, request: Request, response: Response
    ) -> None:
        """Rate-limit gate для одного запроса.

        2026-10-15 fix (regression): аннотации обязаны быть именно
        ``starlette`` ``Request``/``Response`` — как в upstream. FastAPI
        special-cases эти типы (параметры не попадают в HTTP-контракт),
        а ``Any`` превращал их в **required query params** ``?request=&response=``
        в OpenAPI и в 422 на реальном вызове (например, POST
        ``/api/v1/invocations``). Не менять на ``Any``.
        """
        route_index = 0
        dep_index = 0
        for i, route in enumerate(request.app.routes):
            # Safe path resolution: APIRoute имеет .path, _IncludedRouter имеет .prefix.
            # None для роутов без path/prefix (lifespan, mounts) — пропускаем.
            route_path = getattr(route, "path", None) or getattr(route, "prefix", None)
            if route_path is None:
                continue
            # Совпадение path OR prefix (sub-router match: /api/v1/invocations
            # начинается с /api/v1/invocations — точное равенство для leaf).
            if not (
                request.scope["path"] == route_path
                or request.scope["path"].startswith(route_path.rstrip("/") + "/")
            ):
                continue
            route_methods = getattr(route, "methods", None)
            if route_methods is None or request.method not in route_methods:
                continue
            route_index = i
            # Check if the route endpoint has _skip_limiter attribute
            if hasattr(route, "endpoint") and getattr(
                route.endpoint, "_skip_limiter", False
            ):
                return
            for j, dependency in enumerate(route.dependencies):
                if self is dependency.dependency:
                    dep_index = j
                    break

        rate_key = await self.identifier(request)
        key = f"{rate_key}:{route_index}:{dep_index}"
        success = await self.limiter.try_acquire_async(key, blocking=self.blocking)
        if not success:
            return await self.callback(request, response)


@lru_cache(maxsize=1)
def get_default_limiter() -> RedisLimiterAdapter:
    """Singleton ``RedisLimiterAdapter`` по конфигу ``secure_settings``.

    S168 W11 P1-3: Redis-backed (multi-instance safe). Pyrate_limiter был
    in-memory (per-process), что давало N×configured rate limit при N replicas.
    """
    return RedisLimiterAdapter(
        rate_limit=secure_settings.rate_limit,
        window_seconds=secure_settings.rate_time_measure_seconds,
    )


@lru_cache(maxsize=1)
def get_default_rate_limiter() -> RateLimitDependency:
    """Singleton ``RateLimiter``-зависимость с дефолтными identifier/callback.

    Кэшируется, чтобы все ``Depends(get_default_rate_limiter())`` ссылались
    на один объект — FastAPI дедуплицирует одинаковые зависимости в графе
    запроса.

    ``blocking=False`` — превышение лимита моментально возвращает 429
    через ``default_callback``, в отличие от блокирующего ожидания.

    2026-10-15: используем :class:`SafeRateLimiter` (subclass) вместо
    upstream :class:`RateLimitDependency` — fix для _IncludedRouter.path
    AttributeError на вложенных роутерах (например,
    ``/api/v1/invocations``). Upstream ``RateLimitDependency`` алиасится
    на :class:`SafeRateLimiter` через эту функцию; прямые импорты
    :class:`RateLimitDependency` остаются работоспособными.
    """
    return SafeRateLimiter(
        limiter=get_default_limiter(),  # type: ignore[arg-type]  # RedisLimiterAdapter matches Limiter protocol (try_acquire_async)
        identifier=default_identifier,
        callback=default_callback,
        blocking=False,
    )
