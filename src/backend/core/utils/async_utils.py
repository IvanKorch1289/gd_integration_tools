"""AsyncUtils (S171 M27+, D291).

Pattern (D291, Ponytail): thin helpers, no abstractions.
"""
# ruff: noqa: E501
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Iterable
from typing import TypeVar

from src.backend.core.logging import get_logger

_logger = get_logger("core.utils.async_utils")

__all__ = ("gather_with_timeout", "safe_gather", "run_sync_in_thread")

T = TypeVar("T")


async def gather_with_timeout(
    tasks: Iterable[Awaitable[T]],
    *,
    timeout: float = 30.0,
) -> AsyncIterator[T]:
    """Async iterator yielding results as tasks complete (with overall timeout)."""
    pending = list(tasks)
    try:
        results = await asyncio.wait_for(asyncio.gather(*pending), timeout=timeout)
        for r in results:
            yield r
    except asyncio.TimeoutError:
        _logger.warning("async_utils.gather_timeout timeout=%.1f", timeout)


async def safe_gather(
    tasks: Iterable[Awaitable[T]],
    *,
    return_exceptions: bool = True,
) -> list[T | BaseException]:
    """Gather with errors logged but not raised."""
    results = await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    for r in results:
        if isinstance(r, BaseException):
            _logger.warning("async_utils.task_failed err=%s", r)
    return results


def run_sync_in_thread(sync_fn, *args, **kwargs):
    """Run sync function in thread (D291 + D140 backward compat)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_in_executor(None, sync_fn, *args, **kwargs)
    finally:
        loop.close()
