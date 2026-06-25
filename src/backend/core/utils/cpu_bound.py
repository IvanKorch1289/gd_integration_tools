"""CPU-bound helper (S171 M6 — performance).

Для RPA операций (PDF, OCR, image resize) которые требуют CPU.
Pattern: ProcessPoolExecutor для heavy CPU (parallel across cores),
asyncio.to_thread для I/O-bound (parallel within event loop).

Example::

    result = await run_cpu_bound(_merge_pdfs, pdf_bytes_list)
    result = await run_cpu_bound(_ocr_image, image, use_process_pool=True)
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import TypeVar

T = TypeVar("T")

__all__ = ("run_cpu_bound", "default_cpu_pool", "PROCESS_POOL_SIZE")

# Default pool size = cpu_count - 1 (reserve 1 for asyncio loop)
PROCESS_POOL_SIZE: int = max(1, (os.cpu_count() or 2) - 1)

_default_pool: ProcessPoolExecutor | None = None


def default_cpu_pool() -> ProcessPoolExecutor:
    """Singleton ProcessPoolExecutor (lazy init).

    Использовать для CPU-bound tasks: PDF merge, OCR, image resize, hash.

    Returns:
        ProcessPoolExecutor с ``max_workers=cpu_count - 1``.
    """
    global _default_pool
    if _default_pool is None:
        _default_pool = ProcessPoolExecutor(max_workers=PROCESS_POOL_SIZE)
    return _default_pool


async def run_cpu_bound(
    fn: Callable[..., T],
    *args: object,
    use_process_pool: bool = False,
    **kwargs: object,
) -> T:
    """Run CPU-bound function без блокировки event loop.

    Args:
        fn: Sync function (CPU-bound).
        *args: Positional args для fn.
        use_process_pool: True → ProcessPoolExecutor (parallel across cores),
            False → asyncio.to_thread (parallel within loop, lightweight).
        **kwargs: Keyword args для fn.

    Returns:
        Результат fn.

    Example:
        result = await run_cpu_bound(_merge_pdfs, pdf_bytes_list)
    """
    if use_process_pool:
        # ProcessPoolExecutor requires picklable top-level functions.
        # Lambda/closure/local fn → fallback to thread pool + warning.
        import pickle
        try:
            pickle.dumps(fn)
            picklable = True
        except (pickle.PicklingError, TypeError, AttributeError):
            picklable = False
        if not picklable:
            from src.backend.core.logging import get_logger
            get_logger(__name__).warning(
                "cpu_bound: use_process_pool=True requires picklable fn, "
                "got %s — falling back to asyncio.to_thread",
                getattr(fn, "__qualname__", repr(fn)),
            )
            return await asyncio.to_thread(fn, *args, **kwargs)
        loop = asyncio.get_running_loop()
        bound = partial(fn, *args, **kwargs)
        return await loop.run_in_executor(default_cpu_pool(), bound)
    return await asyncio.to_thread(fn, *args, **kwargs)
