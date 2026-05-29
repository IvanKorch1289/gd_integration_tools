"""Global ASGI rate-limit middleware (S18 W7 — per-route + per-tenant extension).

История:
    * S16 W2 (``[wave:s16/k5-w2-global-ratelimit-mw]``): scaffold с
      feature-flag default-OFF + FakeRateLimitChecker.
    * S18 W7 (``[wave:s18/k5-w1-rate-limit-global-mw]``): расширение —
      per-route override (path-prefix dict) + tenant-aware identifier
      (приоритет X-Tenant-ID → fallback client.host) +
      :class:`RedisRateLimitChecker` adapter для fastapi-limiter
      (production backend).

Поведение:

* При ``multi_tenant_rate_limit_enabled=False`` (default) и при
  отсутствии явного ``feature_enabled`` — middleware прозрачен
  (pass-through). При наличии ``feature_enabled=lambda: True`` —
  работает (для unit-тестов / explicit wiring).
* При активном middleware проверяет лимит через
  :class:`RateLimitChecker` с per-route override и tenant-aware
  идентификатором.
* На превышении — отвечает 429 ``Too Many Requests`` с заголовками
  ``Retry-After`` и ``X-RateLimit-Remaining``.

Per-route override (S18 W7):
    Параметр ``route_limits: dict[str, tuple[int, float]]`` —
    ``{path_prefix: (max_per_window, window_seconds)}``. Longest-prefix
    match на ``scope["path"]``. Miss → global default из ``checker``.

Per-tenant identifier (S18 W7):
    Из заголовков по приоритету: ``X-Tenant-ID`` → ``X-User-ID`` →
    ``client.host``. Casbin/OPA integration — carryover S19+.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = (
    "GlobalRateLimitMiddleware",
    "RateLimitChecker",
    "RateLimitConfig",
    "FakeRateLimitChecker",
    "RedisRateLimitChecker",
    "tenant_aware_identifier",
)

_logger = logging.getLogger("entrypoints.middlewares.global_ratelimit")


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Per-route rate-limit configuration.

    Attributes:
        max_per_window: Maximum requests allowed per window.
        window_seconds: Duration of the rate-limit window in seconds.
    """

    max_per_window: int
    window_seconds: float


@runtime_checkable
class RateLimitChecker(Protocol):
    """Контракт rate-limit-проверки.

    Реализация (carryover S17) обёртывает ``fastapi-limiter`` поверх
    Redis. Для unit-тестов используется [FakeRateLimitChecker].
    """

    async def check(self, identifier: str) -> tuple[bool, int, int]:
        """Проверить лимит для идентификатора.

        Args:
            identifier: Уникальный ключ (tenant_id/client_ip/correlation_id).

        Returns:
            (allowed, remaining, retry_after_seconds). Если allowed=False —
            ``retry_after_seconds`` указывает через сколько сек повторить.
        """

    async def check_route_override(self, route: str) -> RateLimitConfig | None:
        """Возвращает per-route override для заданного route.

        Args:
            route: The route path to check for override.

        Returns:
            :class:`RateLimitConfig` если есть override для route,
            иначе ``None``.
        """


class FakeRateLimitChecker:
    """In-memory token-bucket для тестов и default scaffold.

    Простая токен-bucket-логика: ``max_per_window`` запросов в окне
    ``window_seconds`` секунд. Полезна для unit-тестов middleware и
    в dev_light до подключения реального backend.
    """

    def __init__(
        self, *, max_per_window: int = 100, window_seconds: float = 60.0
    ) -> None:
        """Инициализация bucket'а.

        Args:
            max_per_window: Лимит запросов в окне.
            window_seconds: Размер окна в секундах.
        """
        from time import monotonic

        self._max = max_per_window
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = {}
        self._monotonic = monotonic

    async def check(self, identifier: str) -> tuple[bool, int, int]:
        """Проверить лимит — см. [RateLimitChecker.check]."""
        now = self._monotonic()
        history = self._buckets.setdefault(identifier, [])
        # Удалить устаревшие записи.
        cutoff = now - self._window
        history[:] = [t for t in history if t > cutoff]
        if len(history) >= self._max:
            oldest = history[0]
            retry_after = max(1, int(oldest + self._window - now))
            return False, 0, retry_after
        history.append(now)
        remaining = self._max - len(history)
        return True, remaining, 0

    async def check_route_override(self, route: str) -> RateLimitConfig | None:
        """FakeRateLimitChecker не поддерживает route-level overrides."""
        return None


def tenant_aware_identifier(scope: dict[str, Any]) -> str:
    """Tenant-aware identifier для rate-limit (S18 W7).

    Приоритет:
        1. ``X-Tenant-ID`` (multi-tenant deployments).
        2. ``X-User-ID`` (per-user limits).
        3. ``scope["client"][0]`` — IP fallback (anonymous traffic).

    Args:
        scope: ASGI scope (HTTP).

    Returns:
        Идентификатор (``tenant:<id>``, ``user:<id>``, ``ip:<host>``).
    """
    headers = dict(scope.get("headers") or ())
    tenant = headers.get(b"x-tenant-id")
    if tenant:
        return f"tenant:{tenant.decode('latin-1', errors='replace')}"
    user = headers.get(b"x-user-id")
    if user:
        return f"user:{user.decode('latin-1', errors='replace')}"
    client = scope.get("client") or ("-", 0)
    host = client[0] if isinstance(client, (list, tuple)) else "-"
    return f"ip:{host}"


class RedisRateLimitChecker:
    """Production RateLimitChecker через ``fastapi-limiter`` Redis backend (S18 W7).

    Использует sliding-window-counter pattern на Redis: incr+expire под
    ключом ``ratelimit:{identifier}:{window_bucket}``. Fail-open: при
    ошибке Redis — pass-through (advisor pattern: не превращать
    rate-limit в SPoF).

    Args:
        redis: redis.asyncio.Redis клиент (или совместимый proxy).
        max_per_window: Лимит запросов в окне.
        window_seconds: Размер окна в секундах.
        key_prefix: Префикс Redis-ключей (default ``"ratelimit:"``).
        route_overrides_hash: Optional Redis hash key for per-route overrides
            (e.g., ``"ratelimit:route_overrides"``). Hash stores
            ``{route_prefix: "max_per_window:window_seconds"}``.
    """

    def __init__(
        self,
        redis: Any,
        *,
        max_per_window: int = 100,
        window_seconds: float = 60.0,
        key_prefix: str = "ratelimit:",
        route_overrides_hash: str | None = None,
    ) -> None:
        self._redis = redis
        self._max = max_per_window
        self._window = window_seconds
        self._prefix = key_prefix
        self._route_overrides_hash = route_overrides_hash

    async def check(self, identifier: str) -> tuple[bool, int, int]:
        """Проверить лимит — см. :meth:`RateLimitChecker.check`."""
        import time  # noqa: PLC0415

        now_bucket = int(time.time() / self._window)
        key = f"{self._prefix}{identifier}:{now_bucket}"
        try:
            current = await self._redis.incr(key)
            if current == 1:
                # Set TTL только на первый incr (минимизация Redis round-trips).
                await self._redis.expire(key, int(self._window) + 1)
        except Exception as exc:  # noqa: BLE001 — fail-open
            _logger.warning(
                "RedisRateLimitChecker failed for identifier=%s: %s", identifier, exc
            )
            return True, self._max, 0

        if current > self._max:
            return False, 0, int(self._window)
        return True, self._max - int(current), 0

    async def check_route_override(self, route: str) -> RateLimitConfig | None:
        """Возвращает per-route override из Redis hash.

        Looks up the longest matching prefix in the route overrides hash.
        """
        if self._route_overrides_hash is None:
            return None

        try:
            # Fetch all route overrides from the hash
            all_overrides = await self._redis.hgetall(self._route_overrides_hash)
            if not all_overrides:
                return None

            # Find the longest matching prefix
            best_match: tuple[str, str] | None = None
            for route_prefix, config_str in all_overrides.items():
                route_prefix_str = (
                    route_prefix.decode("utf-8")
                    if isinstance(route_prefix, bytes)
                    else route_prefix
                )
                if route_prefix_str and route.startswith(route_prefix_str):
                    if best_match is None or len(route_prefix_str) > len(best_match[0]):
                        best_match = (route_prefix_str, config_str)

            if best_match is None:
                return None

            config_str = best_match[1]
            if isinstance(config_str, bytes):
                config_str = config_str.decode("utf-8")

            # Parse "max_per_window:window_seconds"
            parts = config_str.split(":")
            if len(parts) != 2:
                _logger.warning(
                    "Invalid route override config %r for prefix %r",
                    config_str,
                    best_match[0],
                )
                return None

            try:
                max_per_window = int(parts[0])
                window_seconds = float(parts[1])
            except ValueError:
                _logger.warning(
                    "Invalid route override config %r for prefix %r",
                    config_str,
                    best_match[0],
                )
                return None

            return RateLimitConfig(
                max_per_window=max_per_window, window_seconds=window_seconds
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            _logger.warning(
                "RedisRateLimitChecker.check_route_override failed for route=%s: %s",
                route,
                exc,
            )
            return None


class GlobalRateLimitMiddleware:
    """ASGI middleware с feature-flag default-OFF + per-route override.

    Args:
        app: Next ASGI app в цепочке.
        checker: Глобальный :class:`RateLimitChecker` (Redis или Fake).
        feature_enabled: Lambda → bool. None → читать
            ``feature_flags.multi_tenant_rate_limit_enabled`` (S18 W7
            default-OFF).
        identifier_fn: Callable, извлекающий identifier из ASGI scope.
            По умолчанию — :func:`tenant_aware_identifier`.
        route_checkers: Optional ``{path_prefix: RateLimitChecker}`` —
            per-route override. Longest-prefix match на ``scope["path"]``.
            Miss → используется ``checker`` (global default).

    Использование (FastAPI)::

        app.add_middleware(
            GlobalRateLimitMiddleware,
            checker=RedisRateLimitChecker(redis, max_per_window=1000, window_seconds=60),
            route_checkers={
                "/api/v1/heavy": FakeRateLimitChecker(max_per_window=10, window_seconds=60),
            },
        )
    """

    def __init__(
        self,
        app: Callable[..., Any],
        *,
        checker: RateLimitChecker,
        feature_enabled: Callable[[], bool] | None = None,
        identifier_fn: Callable[[dict[str, Any]], str] | None = None,
        route_checkers: Mapping[str, RateLimitChecker] | None = None,
    ) -> None:
        self._app = app
        self._checker = checker
        self._feature_enabled = feature_enabled or self._default_feature_enabled
        self._identifier_fn = identifier_fn or tenant_aware_identifier
        # Сортируем route_checkers по убыванию длины prefix для
        # longest-prefix-match (тот же паттерн что в TimeoutMiddleware S18 W6).
        items = tuple((p, c) for p, c in (route_checkers or {}).items())
        self._route_checkers: tuple[tuple[str, RateLimitChecker], ...] = tuple(
            sorted(items, key=lambda kv: len(kv[0]), reverse=True)
        )

    @staticmethod
    def _default_feature_enabled() -> bool:
        """Lazy-проверка feature-flag ``multi_tenant_rate_limit_enabled``."""
        try:
            from src.backend.core.config.features import feature_flags  # noqa: PLC0415

            return bool(
                getattr(feature_flags, "multi_tenant_rate_limit_enabled", False)
            )
        except Exception as _:  # noqa: BLE001 — best-effort
            return False

    def _resolve_checker(self, path: str) -> RateLimitChecker:
        """Longest-prefix-match среди ``route_checkers``; fallback на global."""
        for prefix, route_checker in self._route_checkers:
            if path.startswith(prefix):
                return route_checker
        return self._checker

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        """ASGI entrypoint: проверка лимита и проксирование."""
        if scope.get("type") != "http" or not self._feature_enabled():
            await self._app(scope, receive, send)
            return

        identifier = self._identifier_fn(scope)
        checker = self._resolve_checker(scope.get("path", ""))
        try:
            allowed, remaining, retry_after = await checker.check(identifier)
        except Exception as exc:  # noqa: BLE001
            # Защитный fallback: если checker упал — пропускаем запрос,
            # чтобы не превратить rate-limit infrastructure в SPoF.
            _logger.warning(
                "rate_limit_checker_failed identifier=%s error=%s",
                identifier,
                repr(exc),
            )
            await self._app(scope, receive, send)
            return

        if allowed:
            await self._app(scope, receive, send)
            return

        # 429 Too Many Requests.
        headers = [
            (b"content-type", b"application/json"),
            (b"retry-after", str(retry_after).encode()),
            (b"x-ratelimit-remaining", str(remaining).encode()),
        ]
        await send({"type": "http.response.start", "status": 429, "headers": headers})
        body = (
            b'{"detail":"Too Many Requests","retry_after":'
            + str(retry_after).encode()
            + b"}"
        )
        await send({"type": "http.response.body", "body": body})
