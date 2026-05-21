"""Global ASGI rate-limit middleware (fastapi-limiter scaffold).

Wave: ``[wave:s16/k5-w2-global-ratelimit-mw]``.

Scaffold для глобального rate-limit поверх всех HTTP endpoints. Default
feature-flag ``global_rate_limit_enabled=False`` чтобы не нарушить текущее
поведение. Реальная привязка к ``fastapi-limiter`` — после добавления
зависимости в pyproject (carryover S17).

Поведение:

* При выключенном flag — pass-through (zero overhead).
* При включённом — проверяет лимит через :class:`RateLimitChecker`.
* На превышении — отвечает 429 ``Too Many Requests`` с заголовками:
  - ``Retry-After: <seconds>``
  - ``X-RateLimit-Limit: <max>``
  - ``X-RateLimit-Remaining: <remaining>``

Per-tenant identification: tenant_id вычисляется из заголовка
``X-Tenant-ID`` либо из ``request.state.tenant_id`` (set ранним middleware).
Fallback — client.host.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

__all__ = ("GlobalRateLimitMiddleware", "RateLimitChecker", "FakeRateLimitChecker")

_logger = logging.getLogger("entrypoints.middlewares.global_ratelimit")


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


class GlobalRateLimitMiddleware:
    """ASGI middleware с feature-flag default-OFF.

    Использование (FastAPI)::

        app.add_middleware(
            GlobalRateLimitMiddleware,
            checker=FakeRateLimitChecker(max_per_window=100, window_seconds=60),
            feature_enabled=lambda: settings.global_rate_limit_enabled,
            identifier_fn=lambda scope: scope.get("headers_dict", {}).get(b"x-tenant-id", b"-").decode(),
        )
    """

    def __init__(
        self,
        app: Callable[..., Any],
        *,
        checker: RateLimitChecker,
        feature_enabled: Callable[[], bool] | None = None,
        identifier_fn: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        """Создать middleware.

        Args:
            app: Next ASGI app в цепочке.
            checker: RateLimitChecker для проверки лимита.
            feature_enabled: Lambda → bool. None = always enabled.
            identifier_fn: Callable вытаскивающий identifier из scope.
                По умолчанию — берёт client.host.
        """
        self._app = app
        self._checker = checker
        self._feature_enabled = feature_enabled or (lambda: True)
        self._identifier_fn = identifier_fn or self._default_identifier

    @staticmethod
    def _default_identifier(scope: dict[str, Any]) -> str:
        """По умолчанию использует client.host из ASGI scope."""
        client = scope.get("client") or ("-", 0)
        host = client[0] if isinstance(client, (list, tuple)) else "-"
        return str(host)

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
        try:
            allowed, remaining, retry_after = await self._checker.check(identifier)
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
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            }
        )
        body = (
            b'{"detail":"Too Many Requests","retry_after":' + str(retry_after).encode() + b"}"
        )
        await send({"type": "http.response.body", "body": body})
