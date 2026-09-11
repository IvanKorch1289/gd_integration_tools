"""IdempotencyService — high-level API + decorator + singleton accessor.

State machine:
1. ``execute_or_replay(key, fn)``:
    - Если entry отсутствует → begin(), выполнить ``fn``, commit().
    - Если entry COMMITTED → вернуть cached ``result`` (``replayed=True``).
    - Если entry PENDING → бросить ``IdempotencyConflict`` (concurrent).
    - Если ``fn`` raised → ``fail()`` (разрешить retry).

2. ``@service.idempotent(key_fn=...)`` — decorator для auto-dedupe.

Backend абстрагирован — production должен использовать Redis или Postgres
backend; ``InMemoryIdempotencyBackend`` только для тестов/dev_light.

Singleton: ``get_idempotency_service()`` — module-level lazy accessor.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from src.backend.core.idempotency.backends.base import (
    IdempotencyBackend,
    IdempotencyEntry,
    IdempotencyOutcome,
)

logger = logging.getLogger(__name__)

__all__ = (
    "IdempotencyConflict",
    "IdempotencyError",
    "IdempotencyService",
    "IdempotencyState",
    "get_idempotency_service",
)


class IdempotencyError(Exception):
    """Base exception для Idempotency Service."""


class IdempotencyConflict(IdempotencyError):
    """Raised when concurrent call with same key is in flight (PENDING)."""


@dataclass(slots=True)
class IdempotencyState:
    """Result of ``execute_or_replay()``.

    Attributes:
        result: Function result (или cached result если replayed).
        replayed: True если результат взят из кеша (не вызывали fn).
        committed: True если entry был COMMITTED до этого вызова.
        conflict: True если concurrent caller уже держит PENDING.

    """

    result: Any = None
    replayed: bool = False
    committed: bool = False
    conflict: bool = False


# Default TTL: 24 hours (matches Stripe's idempotency window).
DEFAULT_TTL_SECONDS = 86400


class IdempotencyService:
    """High-level idempotency coordinator."""

    def __init__(
        self,
        backend: IdempotencyBackend,
        *,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._backend = backend
        self._default_ttl = default_ttl_seconds

    @property
    def backend(self) -> IdempotencyBackend:
        """Backend для test introspection / advanced use cases."""
        return self._backend

    async def execute_or_replay(
        self,
        key: str,
        fn: Callable[[], Awaitable[Any]],
        *,
        ttl_seconds: int | None = None,
    ) -> IdempotencyState:
        """Выполнить ``fn`` или вернуть cached result.

        Args:
            key: Idempotency key (caller-provided, обычно request UUID).
            fn: Async callable для выполнения.
            ttl_seconds: TTL override (default = ``self._default_ttl``).

        Returns:
            :class:`IdempotencyState` с ``result``, ``replayed``, ``committed``.

        Raises:
            IdempotencyConflict: Если другой caller держит PENDING.

        """
        ttl = ttl_seconds or self._default_ttl

        # 1. Check existing entry.
        existing = await self._backend.get(key)
        if existing is not None:
            if existing.state == IdempotencyOutcome.COMMITTED:
                logger.debug(
                    "Idempotency: replay cached result for key=%s", key
                )
                return IdempotencyState(
                    result=existing.result,
                    replayed=True,
                    committed=True,
                )
            if existing.state == IdempotencyOutcome.PENDING:
                logger.warning(
                    "Idempotency: conflict — concurrent in-flight for key=%s",
                    key,
                )
                return IdempotencyState(conflict=True)

        # 2. Begin (lock).
        outcome = await self._backend.begin(key, ttl)
        if outcome == IdempotencyOutcome.LOCKED:
            return IdempotencyState(conflict=True)
        if outcome == IdempotencyOutcome.COMMITTED:
            # Race: другой caller только что зафиксировал. Replay.
            existing = await self._backend.get(key)
            if existing is not None:
                return IdempotencyState(
                    result=existing.result,
                    replayed=True,
                    committed=True,
                )

        # 3. Execute fn.
        try:
            result = await fn()
        except Exception as exc:
            await self._backend.fail(key, error=str(exc))
            raise

        # 4. Commit.
        await self._backend.commit(key, result)
        return IdempotencyState(result=result, replayed=False, committed=True)

    def idempotent(
        self,
        key_fn: Callable[..., str],
        *,
        ttl_seconds: int | None = None,
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Decorator: auto-dedupe по ``key_fn(args, kwargs)``.

        Args:
            key_fn: ``Callable[[args, kwargs], str]`` — возвращает
                idempotency key для каждого вызова.
            ttl_seconds: TTL override.

        Usage::

            svc = get_idempotency_service()

            @svc.idempotent(key_fn=lambda args, kwargs: f"order:{args[0]}")
            async def create_order(order_id: str, amount: int):
                ...

        """
        def decorator(
            fn: Callable[..., Awaitable[Any]],
        ) -> Callable[..., Awaitable[Any]]:
            @functools.wraps(fn)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                key = key_fn(args, kwargs)
                state = await self.execute_or_replay(
                    key, lambda: fn(*args, **kwargs), ttl_seconds=ttl_seconds
                )
                if state.conflict:
                    raise IdempotencyConflict(
                        f"Concurrent in-flight call for idempotency_key={key!r}"
                    )
                return state.result

            # Сохраняем метаданные для introspection.
            wrapper.__idempotency_key_fn__ = key_fn  # type: ignore[attr-defined]
            wrapper.__idempotency_ttl__ = ttl_seconds  # type: ignore[attr-defined]
            return wrapper

        return decorator


# Singleton — lazy initialization с in-memory backend по default.
_service: IdempotencyService | None = None


def get_idempotency_service() -> IdempotencyService:
    """Module-level singleton accessor (lazy init с in-memory backend).

    Production code должен переопределить backend через
    ``_set_idempotency_service()`` или DI.
    """
    global _service
    if _service is None:
        from src.backend.core.idempotency.backends.in_memory import (
            InMemoryIdempotencyBackend,
        )

        _service = IdempotencyService(backend=InMemoryIdempotencyBackend())
    return _service


def _set_idempotency_service(service: IdempotencyService | None) -> None:
    """Override singleton (для production wiring через DI)."""
    global _service
    _service = service


def reset_idempotency_service() -> None:
    """Reset singleton (test-only)."""
    global _service
    _service = None
