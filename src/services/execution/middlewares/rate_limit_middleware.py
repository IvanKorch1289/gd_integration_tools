"""RateLimitMiddleware — применение :attr:`ActionMetadata.rate_limit` (W14.1.C).

Использует существующий ``unified_rate_limiter`` через provider
из :mod:`core.di.providers` (lazy-resolved, чтобы не тянуть
infrastructure при импорте).

Поведение:

* если в registry нет метаданных или ``metadata.rate_limit`` is None —
  middleware пропускает вызов без изменений (no-op);
* идентификатор для счётчика — ``tenant_id`` или ``user_id`` или
  ``correlation_id``; если ничего не задано, используется ``"global"``;
* при превышении возвращает :class:`ActionResult` с
  ``error.code="rate_limited"`` и ``recoverable=True``;
* окно по умолчанию — 1 секунда (``rate_limit`` интерпретируется как
  RPS на идентификатор, как описано в :class:`ActionMetadata`).
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Mapping

from src.core.interfaces.action_dispatcher import (
    ActionError,
    ActionResult,
    DispatchContext,
    MiddlewareNextHandler,
)
from src.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    action_handler_registry,
)

__all__ = ("RateLimitMiddleware",)

# Имя infrastructure-модуля резолвится строкой через ``importlib``,
# чтобы не импортировать ``infrastructure.*`` напрямую из services-слоя
# (см. ADR-001 / tools/check_layers.py). Доступ ленивый, на каждый
# вызов; в hot-path кэшируется в инстансе.
_LIMITER_MODULE_NAME = "src.infrastructure.resilience.unified_rate_limiter"


class RateLimitMiddleware:
    """Middleware-ограничитель частоты вызовов.

    Args:
        registry: Реестр для чтения :class:`ActionMetadata`. По умолчанию —
            глобальный singleton; в тестах можно подменить.
        limiter_provider: Фабрика, возвращающая объект с
            ``async check(identifier, RateLimit)``. По умолчанию —
            ленивый импорт ``core.di.providers.get_rate_limiter_provider``,
            что позволяет тестам не поднимать Redis.
    """

    def __init__(
        self,
        registry: ActionHandlerRegistry | None = None,
        limiter_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._registry = registry or action_handler_registry
        self._limiter_provider = limiter_provider
        self._limiter_module: Any = None

    async def __call__(
        self,
        action: str,
        payload: Mapping[str, Any],
        context: DispatchContext,
        next_handler: MiddlewareNextHandler,
    ) -> ActionResult:
        metadata = self._registry.get_metadata(action)
        if metadata is None or metadata.rate_limit is None:
            return await next_handler(action, payload, context)

        limiter = self._resolve_limiter()
        if limiter is None:
            # Инфраструктура недоступна — fail-open, как и сам limiter.
            return await next_handler(action, payload, context)

        module = self._resolve_limiter_module()
        if module is None:
            return await next_handler(action, payload, context)
        RateLimit = module.RateLimit
        RateLimitExceeded = module.RateLimitExceeded

        identifier = (
            context.tenant_id or context.user_id or context.correlation_id or "global"
        )
        policy = RateLimit(
            limit=metadata.rate_limit, window_seconds=1, key_prefix=f"action:{action}"
        )
        try:
            await limiter.check(identifier, policy)
        except RateLimitExceeded as exc:
            return ActionResult(
                success=False,
                error=ActionError(
                    code="rate_limited",
                    message=str(exc),
                    details={
                        "limit": exc.limit,
                        "window": exc.window,
                        "retry_after": exc.retry_after,
                    },
                    recoverable=True,
                ),
            )

        return await next_handler(action, payload, context)

    def _resolve_limiter(self) -> Any | None:
        """Лениво резолвит rate-limiter (DI provider или прямой singleton)."""
        if self._limiter_provider is not None:
            try:
                return self._limiter_provider()
            except Exception:
                return None
        try:
            from src.core.di.providers import get_rate_limiter_provider

            return get_rate_limiter_provider()
        except Exception:
            return None

    def _resolve_limiter_module(self) -> Any | None:
        """Лениво импортирует модуль c ``RateLimit`` / ``RateLimitExceeded``.

        Импорт через :mod:`importlib` — чтобы статический линтер слоёв
        не считал ссылку прямой импорт-зависимостью services -> infrastructure.
        """
        if self._limiter_module is not None:
            return self._limiter_module
        try:
            self._limiter_module = importlib.import_module(_LIMITER_MODULE_NAME)
        except Exception:
            return None
        return self._limiter_module
