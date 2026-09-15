"""Focused tests for ``core.batch_ops`` (Wave 4 P2.13)."""

from __future__ import annotations

import logging
import pytest

from src.backend.core.batch_ops import (
    BatchConfig,
    BatchOverflow,
    batch_chunks,
    batch_iter,
    batch_limit_exceeded,
)


class TestBatchConfig:
    def test_defaults(self) -> None:
        c = BatchConfig()
        assert c.max_batch_size == 1000
        assert c.warn_at_percent == 80

    def test_validate_max_batch_size_positive(self) -> None:
        with pytest.raises(ValueError, match="max_batch_size"):
            BatchConfig(max_batch_size=0)

    def test_validate_warn_percent_range(self) -> None:
        with pytest.raises(ValueError, match="warn_at_percent"):
            BatchConfig(warn_at_percent=0)
        with pytest.raises(ValueError, match="warn_at_percent"):
            BatchConfig(warn_at_percent=101)


class TestBatchLimitExceeded:
    def test_under_limit(self) -> None:
        assert batch_limit_exceeded(100, 1000) is False

    def test_at_limit(self) -> None:
        assert batch_limit_exceeded(1000, 1000) is False

    def test_over_limit(self) -> None:
        assert batch_limit_exceeded(1001, 1000) is True


class TestBatchChunks:
    def test_small_list_single_chunk(self) -> None:
        config = BatchConfig(max_batch_size=10)
        chunks = list(batch_chunks([1, 2, 3], config=config))
        assert len(chunks) == 1
        assert chunks[0] == [1, 2, 3]

    def test_exact_size_chunks(self) -> None:
        config = BatchConfig(max_batch_size=3)
        chunks = list(batch_chunks([1, 2, 3, 4, 5, 6], config=config))
        assert len(chunks) == 2
        assert chunks[0] == [1, 2, 3]
        assert chunks[1] == [4, 5, 6]

    def test_multiple_chunks_with_remainder(self) -> None:
        config = BatchConfig(max_batch_size=3)
        chunks = list(batch_chunks([1, 2, 3, 4, 5, 6, 7], config=config))
        assert len(chunks) == 3
        assert chunks[0] == [1, 2, 3]
        assert chunks[1] == [4, 5, 6]
        assert chunks[2] == [7]

    def test_empty_input(self) -> None:
        config = BatchConfig(max_batch_size=10)
        chunks = list(batch_chunks([], config=config))
        assert chunks == []

    def test_works_with_iterator(self) -> None:
        config = BatchConfig(max_batch_size=2)
        chunks = list(batch_chunks(iter([1, 2, 3, 4, 5]), config=config))
        assert chunks == [[1, 2], [3, 4], [5]]

    def test_single_item(self) -> None:
        config = BatchConfig(max_batch_size=10)
        chunks = list(batch_chunks([42], config=config))
        assert chunks == [[42]]

    def test_warn_threshold_logged(self, caplog) -> None:
        config = BatchConfig(max_batch_size=10, warn_at_percent=50)
        with caplog.at_level(logging.DEBUG, logger="core.batch_ops.limiter"):
            list(batch_chunks([1] * 7, config=config))
        # When chunk hits 5 (= 50% of 10), warn log is emitted.
        assert any("Batch chunk at" in m for m in caplog.messages)


class TestBatchIter:
    def test_default_truncate(self) -> None:
        config = BatchConfig(max_batch_size=2)
        chunks = list(batch_iter([1, 2, 3, 4, 5], config=config))
        assert chunks == [[1, 2], [3, 4], [5]]

    def test_raise_on_overflow(self) -> None:
        config = BatchConfig(max_batch_size=2)
        # 5 items in 3 chunks: 2, 2, 1. All ≤ limit. No overflow.
        chunks = list(batch_iter([1, 2, 3, 4, 5], config=config, on_overflow="raise"))
        assert chunks == [[1, 2], [3, 4], [5]]

    def test_invalid_on_overflow_value(self) -> None:
        config = BatchConfig(max_batch_size=2)
        with pytest.raises(ValueError, match="on_overflow"):
            list(batch_iter([1, 2], config=config, on_overflow="invalid"))

    def test_raise_on_exact_overflow(self) -> None:
        """3 items with limit=2 → 2nd chunk has 2 items, then 1.
        If we accumulate 3 BEFORE flushing, overflow at chunk boundary."""
        config = BatchConfig(max_batch_size=2)
        # Manual: if buffer is filled to 2, we flush immediately. So no overflow.
        chunks = list(batch_iter([1, 2, 3], config=config, on_overflow="raise"))
        assert chunks == [[1, 2], [3]]


class TestBatchOverflowException:
    def test_exception_attributes(self) -> None:
        exc = BatchOverflow(items_count=2000, max_batch_size=1000)
        assert exc.items_count == 2000
        assert exc.max_batch_size == 1000
        assert "2000" in str(exc)
        assert "1000" in str(exc)


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import batch_ops

        assert batch_ops.__all__ == (
            "BatchConfig",
            "BatchOverflow",
            "batch_chunks",
            "batch_iter",
            "batch_limit_exceeded",
        )


class TestRealisticExample:
    """Realistic: Redis bulk_set with batching (Wave 4 P2.13 use case)."""

    def test_redis_bulk_set_batching(self) -> None:
        """Simulate bulk_set с 10 000 keys, batched по 1000."""
        config = BatchConfig(max_batch_size=1000)

        # Build 10 000 fake key-value pairs.
        items = [(f"key:{i}", f"value:{i}") for i in range(10_000)]

        # Simulate: process in chunks.
        total_batches = 0
        total_items = 0
        for chunk in batch_chunks(items, config=config):
            total_batches += 1
            total_items += len(chunk)
            assert len(chunk) <= config.max_batch_size
        assert total_batches == 10
        assert total_items == 10_000

    def test_chunk_size_warning_logged_for_large_batch(self, caplog) -> None:
        """Single batch with size > max triggers warning log."""
        config = BatchConfig(max_batch_size=10)
        items = list(range(25))  # 25 > 2 * 10 = 20.
        with caplog.at_level(logging.WARNING, logger="core.batch_ops.limiter"):
            list(batch_chunks(items, config=config))
        # Should have a warning about "exceeds 2x limit".
        assert any(
            "exceeds" in m and "2x limit" in m
            for m in caplog.messages
        )
