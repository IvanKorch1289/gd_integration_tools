"""Request timeout middleware с per-route override (S18 W6, cycle 50 pure ASGI).

Поведение:
    * При ``per_route_timeout_enabled=False`` (default) — global timeout
      из ``settings.secure.request_timeout`` (legacy S0+ behaviour).
    * При flag=ON и наличии ``route_timeouts`` registry — longest-prefix
      match на ``request.url.path``. Match → используется ``total`` из
      registry. Miss → fallback на global default.

Источник registry (build at lifespan):
    Из :class:`RouteManifest.timeout` (``[timeout].total``) либо из
    DSL ``.policy.timeout(total=...)``. Wiring (RouteLoader →
    TimeoutMiddleware) — отдельная wave; сейчас registry опционален.

Cycle 50: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-49 (L1 middlewares).

Cycle 50 design: timeout через ``asyncio.wait_for(call_next(...), timeout=...)``.
В BaseHTTPMiddleware версии тот же pattern (wait_for на dispatch).
Pure ASGI: тот же pattern в ``__call__`` (timeout обёрнут вокруг
``await self.app(scope, receive, send)``).
"""

from __future__ import annotations

import json
from asyncio import wait_for
from collections.abc import Mapping

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.config.settings import settings
from src.backend.core.di.providers import get_app_logger_provider

__all__ = ("TimeoutMiddleware",)


class TimeoutMiddleware:
    """Pure ASGI middleware для ограничения времени обработки запросов (S18 W6).

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
        (single global timeout).

    """

    def __init__(
        self, app: ASGIApp, *, route_timeouts: Mapping[str, float] | None = None
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            route_timeouts: Опциональный registry per-route timeouts.

        """
        self.app = app
        # Сортируем по убыванию длины для longest-prefix-match.
        # Frozen tuple избегает мутаций после lifespan-bootstrap.
        items = tuple((p, float(t)) for p, t in (route_timeouts or {}).items())
        self._route_timeouts: tuple[tuple[str, float], ...] = tuple(
            sorted(items, key=lambda kv: len(kv[0]), reverse=True)
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Обрабатывает запрос с per-route, deadline-budget или global timeout.

        Приоритет (ADR-0305, deadline propagation):
            1. ``RequestContext.deadline_budget.remaining()`` (если уже
               создан middleware выше по цепочке — обычно RequestContextMiddleware).
            2. Per-route timeout из ``route_timeouts`` registry (legacy S18 W6).
            3. ``settings.secure.request_timeout`` (global fallback).

        Минимальный из трёх используется: deadline-budget НЕ ДОЛЖЕН превышать
        per-route limit, чтобы не снимать защиту, выставленную оператором.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        timeout_seconds = self._resolve_timeout(path)

        # ADR-0305: если upstream-middleware уже создал DeadlineBudget и
        # request ещё в его рамках — сужаем timeout до remaining.
        try:
            from src.backend.core.request_context import RequestContext

            ctx = RequestContext.current()
            if ctx is not None and ctx.deadline_budget is not None:
                remaining = ctx.deadline_budget.remaining()
                path_prefix = self._normalize_path_prefix(path)
                if remaining <= 0.0:
                    # Deadline уже истёк — НЕ запускаем downstream, сразу 408.
                    # Это и есть admission control: overload → контролируемый отказ.
                    get_app_logger_provider().warning(
                        "Deadline budget expired before request processing: %s", path
                    )
                    try:
                        from src.backend.infrastructure.observability.metrics import (
                            record_deadline_budget_expired_at_entry,
                            record_deadline_budget_remaining,
                        )

                        record_deadline_budget_remaining(
                            0.0, path_prefix=path_prefix, outcome="expired_at_entry"
                        )
                        record_deadline_budget_expired_at_entry(path_prefix)
                    except Exception:
                        pass  # metrics must not break request flow
                    await self._send_408(send)
                    return
                timeout_seconds = min(timeout_seconds, remaining)
                # Record remaining budget for observability (histogram).
                try:
                    from src.backend.infrastructure.observability.metrics import (
                        record_deadline_budget_remaining,
                    )

                    record_deadline_budget_remaining(
                        remaining, path_prefix=path_prefix, outcome="processed"
                    )
                except Exception:
                    pass
        except Exception:
            # Не ломаем request, если RequestContext недоступен.
            pass

        try:
            # Cycle 50 critical: wait_for обёрнут вокруг downstream.
            # Если downstream не отвечает в timeout — asyncio.TimeoutError.
            await wait_for(self.app(scope, receive, send), timeout=timeout_seconds)
        except TimeoutError:
            get_app_logger_provider().warning(
                "Превышено время обработки запроса: %s (timeout=%.2fs)",
                scope.get("path", ""),
                timeout_seconds,
            )
            await self._send_408(send)

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
    def _normalize_path_prefix(path: str) -> str:
        """Извлечь первый non-empty сегмент path для метрик (cardinality guard).

        Examples:
            ``/api/v1/orders`` → ``/api``
            ``/api`` → ``/api``
            ``/`` → ``/``
            ``""`` → ``/``
            ``api/v1/orders`` (no leading slash) → ``/api``

        Используется как ``path_prefix`` label в Prometheus метриках
        (deadline_budget_remaining_seconds, deadline_budget_expired_at_entry_total),
        чтобы избежать high-cardinality explosion на динамических URL
        (например, ``/api/v1/orders/{order_id}`` → все идут под ``/api``).
        """
        if not path:
            return "/"
        # Strip leading/trailing slashes, взять первый сегмент.
        # ``"/api/v1/".strip("/")`` → ``"api/v1"``, ``split("/", 1)[0]`` → ``"api"``.
        stripped = path.strip("/")
        if not stripped:
            return "/"
        first_segment = stripped.split("/", 1)[0]
        return "/" + first_segment

    @staticmethod
    def _is_per_route_enabled() -> bool:
        """Lazy-проверка feature-flag ``per_route_timeout_enabled``."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(getattr(feature_flags, "per_route_timeout_enabled", False))
        except (ImportError, AttributeError, RuntimeError) as ff_exc:
            # cycle-9/D-AUDIT-1004: narrow exceptions + observability.
            # ImportError — features module missing, AttributeError —
            # config not initialized, RuntimeError — feature_flags unavailable.
            import logging

            logging.getLogger(__name__).debug(
                "timeout_middleware.feature_flag_fallback", extra={"error": str(ff_exc)}
            )
            return False

    @staticmethod
    async def _send_408(send: Send) -> None:
        """Отправляет 408 JSON response через send (cycle 39 no-raise pattern)."""
        body = json.dumps({"detail": "Превышено время обработки запроса"}).encode(
            "utf-8"
        )
        await send(
            {
                "type": "http.response.start",
                "status": 408,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
