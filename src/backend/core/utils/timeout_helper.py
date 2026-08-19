"""Timeout helper (S171 M5 — централизация для 8+ scattered call sites).

Единый wrapper над :func:`asyncio.timeout` с structured logging на slow_call
и context-manager для inline-использования.

Round 6 (K-1.1, S171 W5+): миграция ``asyncio.wait_for`` →
:func:`asyncio.timeout` context manager (Python 3.11+, проект на 3.14).
Преимущества:

* Cancellation работает на nested scopes, не только на top-level.
* Поддерживает async-генераторы и async comprehensions.
* Stack-trace включает актуальный duration.

Pattern (Ponytail, D139): thin wrapper без абстракций.
Заменяет дубли в jupyter_mixin / health / gateway / agent_sandbox /
lineage / sla_alerting.

Example::

    result = await with_timeout(
        fetch_data(), timeout=5.0,
        op="http.fetch", slow_threshold=2.0,
    )
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import TypeVar

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)

T = TypeVar("T")

__all__ = ("with_timeout",)


async def with_timeout[T](
    coro: Awaitable[T],
    *,
    timeout: float,
    op: str | None = None,
    slow_threshold: float | None = None,
) -> T:
    """Run ``coro`` with timeout.

    Args:
        coro: Awaitable для исполнения.
        timeout: Таймаут в секундах.
        op: Имя операции (для логирования).
        slow_threshold: Логировать warning если ``slow_threshold`` > 0 и
            фактическое время превысило порог. ``None`` отключает логирование.

    Returns:
        Результат ``coro``.

    Raises:
        TimeoutError: Если таймаут истёк до завершения ``coro``
            (в Python 3.11+ ``asyncio.TimeoutError`` ≡ ``builtins.TimeoutError``).

    """
    start = time.monotonic()
    try:
        # Round 6 K-1.1: asyncio.timeout context manager (Py 3.11+)
        # вместо asyncio.wait_for — лучше семантика cancellation,
        # поддержка nested scopes.
        async with asyncio.timeout(timeout):
            result = await coro
    except TimeoutError:
        elapsed = time.monotonic() - start
        _logger.warning(
            "timeout op=%s elapsed=%.3fs limit=%.3fs", op or "?", elapsed, timeout
        )
        raise
    if slow_threshold and op:
        elapsed = time.monotonic() - start
        if elapsed >= slow_threshold:
            _logger.warning(
                "slow_call op=%s elapsed=%.3fs threshold=%.3fs",
                op,
                elapsed,
                slow_threshold,
            )
    return result
