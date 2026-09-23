"""Batch Operations — bounded batch utilities (Wave 4 P2.13).

Защита от OOM при bulk операциях (Redis bulk_get/set, ClickHouse insert,
и т.п.). Каждая batch chunked по ``max_batch_size`` records.

Использование::

    from src.backend.core.batch_ops import (
        BatchConfig, batch_iter, batch_chunks, batch_limit_exceeded,
    )

    config = BatchConfig(max_batch_size=1000, warn_at_percent=80)

    # Stream chunks of a list.
    for chunk in batch_chunks(huge_list, config):
        redis.mset(chunk)

    # Raise on overflow.
    for batch in batch_iter(stream, config, on_overflow="raise"):
        process(batch)
"""

from __future__ import annotations

from src.backend.core.batch_ops.limiter import (
    BatchConfig,
    BatchOverflow,
    batch_chunks,
    batch_iter,
    batch_limit_exceeded,
)

__all__ = (
    "BatchConfig",
    "BatchOverflow",
    "batch_chunks",
    "batch_iter",
    "batch_limit_exceeded",
)
