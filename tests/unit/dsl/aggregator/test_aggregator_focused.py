"""Focused tests for ``core.dsl.aggregator`` (Wave 4 P4.19)."""

from __future__ import annotations

import time

import pytest

from src.backend.dsl.aggregator import (
    AggregatedBatch,
    AggregatorConfig,
    CompletionStrategy,
    Message,
    aggregate,
    aggregate_stream,
)


def _msg(key: str, value: float = 1.0, ts: float = 0.0) -> Message:
    """Create a test Message with given correlation key."""
    return Message(
        body={"customer_id": key, "amount": value},
        headers={"customer_id": key},
        timestamp=ts,
    )


class TestConfig:
    def test_defaults(self) -> None:
        c = AggregatorConfig(
            correlation_key="customer_id", completion_size=10
        )
        assert c.completion_strategy == CompletionStrategy.LIST
        assert c.completion_timeout is None

    def test_validate_must_have_completion(self) -> None:
        with pytest.raises(ValueError, match="completion"):
            AggregatorConfig(correlation_key="k")

    def test_validate_custom_requires_reducer(self) -> None:
        with pytest.raises(ValueError, match="custom_reducer"):
            AggregatorConfig(
                correlation_key="k",
                completion_size=1,
                completion_strategy=CompletionStrategy.CUSTOM,
            )

    def test_validate_correlation_key_callable(self) -> None:
        c = AggregatorConfig(
            correlation_key=lambda m: m.headers["k"],
            completion_size=1,
        )
        assert callable(c.correlation_key)


class TestKeyExtraction:
    def test_string_correlation_key(self) -> None:
        c = AggregatorConfig(
            correlation_key="customer_id", completion_size=3,
        )
        m = _msg("c1")
        # Headers dict → key extraction.
        assert c.correlation_key in m.headers

    def test_callable_correlation_key(self) -> None:
        c = AggregatorConfig(
            correlation_key=lambda m: m.body["type"], completion_size=1,
        )
        m = Message(body={"type": "alpha"}, headers={}, timestamp=0.0)
        assert c.correlation_key(m) == "alpha"


class TestAggregateBasic:
    def test_size_completion(self) -> None:
        """Flush when N messages accumulated."""
        msgs = [_msg("c1", i + 1) for i in range(5)]
        config = AggregatorConfig(
            correlation_key="customer_id", completion_size=3,
        )
        batches = aggregate(msgs, config=config)
        # 5 messages / 3 per batch = 1 complete batch + 1 partial.
        assert len(batches) == 2
        assert batches[0].size == 3
        assert batches[0].key == "c1"
        assert batches[1].size == 2

    def test_timeout_completion(self) -> None:
        """Flush after T seconds."""
        base = 1000.0
        msgs = [
            _msg("c1", 1.0, ts=base),
            _msg("c1", 2.0, ts=base + 6),  # elapsed = 6 < 10.
        ]
        config = AggregatorConfig(
            correlation_key="customer_id", completion_timeout=10.0,
        )
        batches = aggregate(msgs, config=config)
        # 2 messages — both stay in pending (elapsed<10).
        # After end of input — partial batch flushed.
        completed = [b for b in batches if b.size > 0]
        assert len(completed) == 1
        assert completed[0].size == 2

    def test_timeout_triggers_fresh(self) -> None:
        """Newer message triggers timeout for older ones."""
        base = 1000.0
        msgs = [
            _msg("c1", 1.0, ts=base),
            _msg("c1", 2.0, ts=base + 12),  # elapsed=12 >= 10 → flush all.
        ]
        config = AggregatorConfig(
            correlation_key="customer_id", completion_timeout=10.0,
        )
        batches = aggregate(msgs, config=config)
        # 2 messages flushed together when timeout reached.
        completed = [b for b in batches if b.size > 0]
        assert len(completed) == 1
        assert completed[0].size == 2

    def test_multi_key_isolation(self) -> None:
        """Different keys aggregated independently."""
        msgs = (
            [_msg("c1", 1.0), _msg("c2", 2.0), _msg("c1", 3.0), _msg("c2", 4.0)]
        )
        config = AggregatorConfig(
            correlation_key="customer_id", completion_size=2,
        )
        batches = aggregate(msgs, config=config)
        # Each key has 2 messages → 2 complete batches.
        assert len(batches) == 2
        assert {b.key for b in batches} == {"c1", "c2"}

    def test_empty_input(self) -> None:
        config = AggregatorConfig(
            correlation_key="k", completion_size=1,
        )
        assert aggregate([], config=config) == []


class TestCombineStrategies:
    def test_list_strategy(self) -> None:
        msgs = [_msg("c1", i) for i in range(3)]
        config = AggregatorConfig(
            correlation_key="k",
            completion_size=3,
            completion_strategy=CompletionStrategy.LIST,
        )
        batches = aggregate(msgs, config=config)
        assert isinstance(batches[0].result, list)
        assert len(batches[0].result) == 3

    def test_first_strategy(self) -> None:
        msgs = [_msg("c1", i + 1) for i in range(3)]  # amounts 1,2,3.
        config = AggregatorConfig(
            correlation_key="k",
            completion_size=3,
            completion_strategy=CompletionStrategy.FIRST,
        )
        batches = aggregate(msgs, config=config)
        assert batches[0].result.body["amount"] == 1.0

    def test_last_strategy(self) -> None:
        msgs = [_msg("c1", i + 1) for i in range(3)]  # amounts 1,2,3.
        config = AggregatorConfig(
            correlation_key="k",
            completion_size=3,
            completion_strategy=CompletionStrategy.LAST,
        )
        batches = aggregate(msgs, config=config)
        assert batches[0].result.body["amount"] == 3.0

    def test_merge_strategy(self) -> None:
        msgs = [
            Message(body={"a": 1, "b": 2}, headers={}, timestamp=0.0),
            Message(body={"a": 2, "b": 3, "c": 4}, headers={}, timestamp=0.0),
            Message(body={"a": 3, "d": 6}, headers={}, timestamp=0.0),
        ]
        config = AggregatorConfig(
            correlation_key=lambda m: str(m.body["a"]),
            completion_size=3,
            completion_strategy=CompletionStrategy.MERGE,
        )
        batches = aggregate(msgs, config=config)
        # First a=1 (only). Subsequent a=2 and a=3 form new keys.
        # Only batch with completion_size=3 is the one with first a=1
        # which never reaches 3. So no batch completes. All end as partial.
        # But actually we have 1 message per key, so each key has size 1.
        # After end-of-input flush, each becomes a partial batch.
        # Let me make the test simpler — use header-based key.
        msgs2 = [
            Message(body={"x": 1, "y": 2}, headers={"k": "1"}, timestamp=0.0),
            Message(body={"y": 3, "z": 4}, headers={"k": "1"}, timestamp=0.0),
            Message(body={"x": 5, "w": 6}, headers={"k": "1"}, timestamp=0.0),
        ]
        config = AggregatorConfig(
            correlation_key="k",
            completion_size=3,
            completion_strategy=CompletionStrategy.MERGE,
        )
        batches = aggregate(msgs2, config=config)
        # 3 messages, all in key "1" → 1 batch with merged body.
        assert len(batches) == 1
        assert batches[0].result == {"x": 5, "y": 3, "z": 4, "w": 6}

    def test_sum_strategy(self) -> None:
        msgs = [
            Message(body={"amount": 10}, headers={}, timestamp=0.0),
            Message(body={"amount": 20}, headers={}, timestamp=0.0),
            Message(body={"amount": 30}, headers={}, timestamp=0.0),
        ]
        config = AggregatorConfig(
            correlation_key="k",
            completion_size=3,
            completion_strategy=CompletionStrategy.SUM,
        )
        batches = aggregate(msgs, config=config)
        assert batches[0].result == 60.0

    def test_custom_strategy(self) -> None:
        msgs = [_msg("c1", i) for i in range(3)]

        def reducer(batch):
            return {"count": len(batch), "sum": sum(m.body["amount"] for m in batch)}

        config = AggregatorConfig(
            correlation_key="k",
            completion_size=3,
            completion_strategy=CompletionStrategy.CUSTOM,
            custom_reducer=reducer,
        )
        batches = aggregate(msgs, config=config)
        assert batches[0].result == {"count": 3, "sum": 3.0}


class TestAggregateStream:
    def test_streaming_yields_completed(self) -> None:
        """Streaming version yields batch on each completion."""
        msgs = [_msg("c1", i) for i in range(7)]
        config = AggregatorConfig(
            correlation_key="k", completion_size=3,
        )
        results = list(aggregate_stream(iter(msgs), config=config))
        # 7 messages / 3 per batch = 2 complete batches.
        assert len(results) == 2
        assert results[0].size == 3
        assert results[1].size == 3


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.dsl import aggregator

        assert aggregator.__all__ == (
            "AggregatedBatch",
            "AggregatorConfig",
            "CompletionStrategy",
            "Message",
            "aggregate",
            "aggregate_stream",
        )


class TestRealisticExample:
    """Realistic: order batching для payment processing."""

    def test_order_batching_payment(self) -> None:
        """Group orders by customer, batch every 5 orders or 30 seconds."""
        base = 1000.0
        msgs = [
            Message(
                body={"customer": "acme", "amount": 100.0},
                headers={"customer": "acme"},
                timestamp=base + i,
            )
            for i in range(8)
        ] + [
            Message(
                body={"customer": "beta", "amount": 50.0},
                headers={"customer": "beta"},
                timestamp=base + i,
            )
            for i in range(3)
        ]

        config = AggregatorConfig(
            correlation_key="customer",
            completion_size=5,
            completion_strategy=CompletionStrategy.SUM,
        )
        batches = aggregate(msgs, config=config)
        # acme: 5 messages → 1 complete batch + 3 pending.
        # beta: 3 messages → 1 partial batch.
        acme_batches = [b for b in batches if b.key == "acme"]
        beta_batches = [b for b in batches if b.key == "beta"]
        # After end-of-input, partial batches are flushed.
        # But some batches may not have completed → still flushed as partial.
        assert any(b.size == 5 for b in acme_batches)  # 1 full batch
        assert any(b.size == 3 for b in acme_batches)  # 1 partial
        # Beta all in one partial batch.
        assert any(b.size == 3 for b in beta_batches)
        # Total: 3 batches.
        assert len(batches) == 3
