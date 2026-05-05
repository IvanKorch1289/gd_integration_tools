"""IdempotencyMiddleware — кэширование результата по ``idempotency_key`` (W14.1.C).

Baseline-реализация хранит ответы в in-memory dict.
Redis-backed реализация подключается позднее через тот же интерфейс
(см. :class:`IdempotencyStore`).

Поведение:

* если :attr:`DispatchContext.idempotency_key` отсутствует — middleware
  пропускает вызов без изменений (no-op);
* если ключ найден в store — возвращается сохранённый
  :class:`ActionResult` (с ``metadata["cached"] = True``) без вызова
  ``next_handler``;
* если ключа нет — выполняется ``next_handler`` и при ``success=True``
  результат кэшируется.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from src.backend.core.interfaces.action_dispatcher import (
    ActionResult,
    DispatchContext,
    MiddlewareNextHandler,
)

__all__ = ("IdempotencyMiddleware", "IdempotencyStore", "InMemoryIdempotencyStore")


class IdempotencyStore(Protocol):
    """Контракт стора для :class:`IdempotencyMiddleware`.

    Минимальный сигнатурный набор — get/set по строковому ключу.
    Redis-backed реализация будет следовать тому же протоколу.
    """

    async def get(self, key: str) -> ActionResult | None:  # pragma: no cover
        ...

    async def set(self, key: str, result: ActionResult) -> None:  # pragma: no cover
        ...


class InMemoryIdempotencyStore:
    """In-memory baseline-реализация :class:`IdempotencyStore`.

    Подходит для одиночного процесса (тесты, dev_light). Для production
    следует подменить на Redis-backed реализацию через ту же фабрику.
    """

    def __init__(self) -> None:
        self._cache: dict[str, ActionResult] = {}

    async def get(self, key: str) -> ActionResult | None:
        return self._cache.get(key)

    async def set(self, key: str, result: ActionResult) -> None:
        self._cache[key] = result


class IdempotencyMiddleware:
    """Middleware с кэшем по ``idempotency_key``.

    Args:
        store: Реализация :class:`IdempotencyStore`. По умолчанию —
            in-memory; Redis-backed подменяется в composition root.
    """

    def __init__(self, store: IdempotencyStore | None = None) -> None:
        self._store: IdempotencyStore = store or InMemoryIdempotencyStore()

    async def __call__(
        self,
        action: str,
        payload: Mapping[str, Any],
        context: DispatchContext,
        next_handler: MiddlewareNextHandler,
    ) -> ActionResult:
        key = context.idempotency_key
        if not key:
            return await next_handler(action, payload, context)

        cached = await self._store.get(self._build_key(action, key))
        if cached is not None:
            metadata: dict[str, Any] = dict(cached.metadata)
            metadata["cached"] = True
            return ActionResult(
                success=cached.success,
                data=cached.data,
                error=cached.error,
                metadata=metadata,
            )

        result = await next_handler(action, payload, context)
        if result.success:
            await self._store.set(self._build_key(action, key), result)
        return result

    @staticmethod
    def _build_key(action: str, idempotency_key: str) -> str:
        """Префиксует ключ именем action для изоляции пространств имён."""
        return f"{action}::{idempotency_key}"
