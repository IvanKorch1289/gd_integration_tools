"""Batch operations limiter — bounded chunking (Wave 4 P2.13).

Pure-Python utility for batched I/O operations (Redis, ClickHouse, etc.).
Provides:
- BatchConfig (max_batch_size, warn_at_percent).
- batch_chunks(iterable, config) → Iterator[list[T]] (splits in chunks).
- batch_iter(iterable, config, on_overflow) → Iterator[list[T]] (raises or truncates).
- batch_limit_exceeded(items_count, max_batch_size) → bool.
- BatchOverflow exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Iterator, TypeVar

logger = logging.getLogger(__name__)

__all__ = (
    "BatchConfig",
    "BatchOverflow",
    "batch_chunks",
    "batch_iter",
    "batch_limit_exceeded",
)

T = TypeVar("T")


class BatchOverflow(Exception):
    """Raised when batch exceeds limit and on_overflow='raise'."""

    def __init__(self, items_count: int, max_batch_size: int) -> None:
        self.items_count = items_count
        self.max_batch_size = max_batch_size
        super().__init__(
            f"Batch size {items_count} exceeds limit {max_batch_size}"
        )


@dataclass(slots=True)
class BatchConfig:
    """Configuration для batched operations (Wave 4 P2.13).

    Attributes:
        max_batch_size: Maximum records per single batch.
        warn_at_percent: Percentage at which to log warning.
    """

    max_batch_size: int = 1000
    warn_at_percent: int = 80

    def __post_init__(self) -> None:
        if self.max_batch_size <= 0:
            raise ValueError("max_batch_size must be > 0")
        if not 0 < self.warn_at_percent <= 100:
            raise ValueError("warn_at_percent must be in (0, 100]")


def batch_limit_exceeded(items_count: int, max_batch_size: int) -> bool:
    """Return True if items_count exceeds max_batch_size."""
    return items_count > max_batch_size


def batch_chunks(
    items: Iterable[T],
    config: BatchConfig,
) -> Iterator[list[T]]:
    """Split iterable into chunks of ``max_batch_size``.

    Logs warning when chunk reaches ``warn_at_percent`` of limit.
    If total items exceed max_batch_size × 2 — logs error.
    """
    chunk: list[T] = []
    warn_threshold = config.max_batch_size * config.warn_at_percent / 100
    total_count = 0
    for item in items:
        chunk.append(item)
        total_count += 1
        if len(chunk) >= config.max_batch_size:
            yield chunk
            chunk = []
        elif len(chunk) >= warn_threshold:
            logger.warning(
                "Batch chunk at %d/%d (%.0f%%)",
                len(chunk), config.max_batch_size,
                100 * len(chunk) / config.max_batch_size,
            )
    if chunk:
        yield chunk

    if total_count > config.max_batch_size * 2:
        logger.warning(
            "Batch total %d exceeds %d (2x limit)",
            total_count, config.max_batch_size,
        )


def batch_iter(
    items: Iterable[T],
    config: BatchConfig,
    *,
    on_overflow: str = "truncate",
) -> Iterator[list[T]]:
    """Stream items в batched chunks.

    Args:
        items: Source iterable.
        config: BatchConfig.
        on_overflow: "truncate" (default) or "raise" (BatchOverflow).

    Returns:
        Iterator of list[T] (each chunk ≤ max_batch_size).

    Raises:
        BatchOverflow: if on_overflow="raise" and chunk accumulates
            more than max_batch_size (overflow).
    """
    if on_overflow not in ("truncate", "raise"):
        raise ValueError(
            f"on_overflow must be 'truncate' or 'raise', got {on_overflow!r}"
        )
    chunk: list[T] = []
    for item in items:
        chunk.append(item)
        # Flush at limit. Overflow only if len > max_batch_size (which means
        # on_overflow='raise' since the chunk flushed at == max_batch_size
        # but then new items accumulated and pushed over).
        if len(chunk) >= config.max_batch_size:
            if (
                on_overflow == "raise"
                and len(chunk) > config.max_batch_size
            ):
                raise BatchOverflow(
                    items_count=len(chunk),
                    max_batch_size=config.max_batch_size,
                )
            yield chunk
            chunk = []
    if chunk:
        if on_overflow == "raise" and len(chunk) > config.max_batch_size:
            raise BatchOverflow(
                items_count=len(chunk),
                max_batch_size=config.max_batch_size,
            )
        yield chunk
