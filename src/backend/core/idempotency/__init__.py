"""Idempotency Service — фундамент для retry-safe write-операций (Wave 1 P0 #1).

Проблема (EP-R1):
    Retry, сетевые ошибки, broker redeliveries и Temporal Activity retries
    приводят к дублирующим side-effects: двойные платежи, повторные заявки,
    дубли файлов, дубли сообщений. На уровне TCP/HTTP гарантии
    at-most-once нет — нужен application-level dedupe.

Решение:
    ``IdempotencyService`` — единая точка дедупликации по ``idempotency_key``
    с двумя backend'ами:

    * :class:`InMemoryIdempotencyBackend` — для unit/integration тестов
      и dev_light (Wave 21.3c in-memory fallback).
    * :class:`RedisIdempotencyBackend` — production (TTL-based).
    * :class:`PostgresIdempotencyBackend` — production (UNIQUE constraint,
      durable через commit — recommended для financial операций).

Использование::

    from src.backend.core.idempotency import get_idempotency_service

    svc = get_idempotency_service()

    # Manual flow:
    state = await svc.execute_or_replay(
        key="order-create:tenant-1:req-uuid-123",
        fn=lambda: create_order(amount=100),
    )
    if state.replayed:
        # Повторный вызов с тем же ключом → возвращён кешированный результат.
        return state.result

    # Декоратор:
    @svc.idempotent(key_fn=lambda args, kwargs: f"order:{args[0]}")
    async def create_order(order_id: str, amount: int):
        ...
"""

from __future__ import annotations

from src.backend.core.idempotency.backends.base import (
    IdempotencyBackend,
    IdempotencyEntry,
    IdempotencyOutcome,
)
from src.backend.core.idempotency.backends.in_memory import InMemoryIdempotencyBackend
from src.backend.core.idempotency.service import (
    IdempotencyService,
    get_idempotency_service,
)

__all__ = (
    "IdempotencyBackend",
    "IdempotencyEntry",
    "IdempotencyOutcome",
    "IdempotencyService",
    "InMemoryIdempotencyBackend",
    "get_idempotency_service",
)
