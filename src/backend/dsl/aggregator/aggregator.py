"""EIP Aggregator — completion-based batching (Wave 4 P4.19).

Pure-Python implementation of Camel EIP Aggregator pattern.
- correlation_key → groups messages into batches.
- completion_size (N messages) OR completion_timeout (T seconds) flushes.
- completion_strategy → how to combine flushed messages.
- thread-safe (single-threaded, suitable for async).
"""

from __future__ import annotations

import enum
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

logger = logging.getLogger(__name__)

__all__ = (
    "AggregatorConfig",
    "CompletionStrategy",
    "Message",
    "aggregate",
    "aggregate_stream",
)


class CompletionStrategy(str, enum.Enum):
    """How to combine flushed batch messages."""

    LIST = "list"  # return list of messages.
    FIRST = "first"  # return first message.
    LAST = "last"  # return last message.
    MERGE = "merge"  # merge dicts (for message.body dicts).
    SUM = "sum"  # sum numeric values from body.
    CUSTOM = "custom"  # user-provided reducer.


@dataclass(slots=True)
class Message:
    """Generic message для aggregation.

    Attributes:
        body: Payload (dict для MERGE/SUM strategies).
        headers: Metadata including correlation key value.
        timestamp: Time of arrival.
    """

    body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass(slots=True)
class AggregatorConfig:
    """Configuration для EIP Aggregator.

    Attributes:
        correlation_key: Extract key value from message (str, callable).
        completion_size: Flush when N messages accumulated (None = no size limit).
        completion_timeout: Flush after T seconds (None = no timeout).
        completion_strategy: How to combine flushed messages.
        custom_reducer: Required if strategy=CUSTOM.
    """

    correlation_key: Callable[[Message], str] | str
    completion_size: int | None = None
    completion_timeout: float | None = None
    completion_strategy: CompletionStrategy = CompletionStrategy.LIST
    custom_reducer: Callable[[list[Message]], Any] | None = None

    def __post_init__(self) -> None:
        if self.completion_size is None and self.completion_timeout is None:
            raise ValueError("Must set completion_size or completion_timeout")
        if (
            self.completion_strategy == CompletionStrategy.CUSTOM
            and self.custom_reducer is None
        ):
            raise ValueError("custom_reducer required for CUSTOM strategy")
        # correlation_key can be either a callable or a string (header name).
        if not (callable(self.correlation_key) or isinstance(self.correlation_key, str)):
            raise ValueError(
                "correlation_key must be callable or string"
            )


@dataclass(slots=True)
class AggregatedBatch:
    """Result of one batch flush.

    Attributes:
        key: Correlation key value.
        result: Aggregated result (type depends on strategy).
        size: Number of messages in batch.
        elapsed: Seconds since first message in batch.
    """

    key: str
    result: Any
    size: int
    elapsed: float = 0.0


def _key_of(msg: Message, key_fn: Callable[[Message], str] | str) -> str:
    """Extract correlation key value."""
    if callable(key_fn):
        return str(key_fn(msg))
    # str → treat as header name.
    return str(msg.headers.get(key_fn, ""))


def _combine(
    messages: list[Message], strategy: CompletionStrategy,
    reducer: Callable[[list[Message]], Any] | None,
) -> Any:
    """Combine flushed messages per strategy."""
    if not messages:
        return None
    if strategy == CompletionStrategy.LIST:
        return list(messages)
    if strategy == CompletionStrategy.FIRST:
        return messages[0]
    if strategy == CompletionStrategy.LAST:
        return messages[-1]
    if strategy == CompletionStrategy.MERGE:
        merged: dict[str, Any] = {}
        for m in messages:
            if isinstance(m.body, dict):
                merged.update(m.body)
        return merged
    if strategy == CompletionStrategy.SUM:
        total = 0.0
        for m in messages:
            for v in (m.body or {}).values():
                if isinstance(v, (int, float)):
                    total += v
        return total
    if strategy == CompletionStrategy.CUSTOM:
        assert reducer is not None
        return reducer(messages)
    return messages


def aggregate(
    messages: Iterable[Message],
    *,
    config: AggregatorConfig,
) -> list[AggregatedBatch]:
    """Aggregate messages into batches по correlation key.

    Args:
        messages: Iterable of Message.
        config: AggregatorConfig.

    Returns:
        List of AggregatedBatch (only when batches are completed).
    """
    batches: list[AggregatedBatch] = []
    pending: dict[str, list[Message]] = defaultdict(list)
    first_seen: dict[str, float] = {}
    key_fn = config.correlation_key

    for msg in messages:
        if msg.timestamp == 0.0:
            msg.timestamp = time.time()
        key = _key_of(msg, key_fn)
        pending[key].append(msg)
        first_seen.setdefault(key, msg.timestamp)

        # Check completion.
        is_complete = False
        elapsed = msg.timestamp - first_seen[key]
        if (
            config.completion_size is not None
            and len(pending[key]) >= config.completion_size
        ):
            is_complete = True
        if (
            config.completion_timeout is not None
            and elapsed >= config.completion_timeout
        ):
            is_complete = True
        if is_complete:
            msgs = pending.pop(key)
            first_seen.pop(key, None)
            result = _combine(msgs, config.completion_strategy, config.custom_reducer)
            batches.append(
                AggregatedBatch(
                    key=key,
                    result=result,
                    size=len(msgs),
                    elapsed=elapsed,
                )
            )
    # Flush remaining.
    for key, msgs in pending.items():
        if not msgs:
            continue
        elapsed = msgs[-1].timestamp - first_seen[key]
        result = _combine(msgs, config.completion_strategy, config.custom_reducer)
        batches.append(
            AggregatedBatch(
                key=key,
                result=result,
                size=len(msgs),
                elapsed=elapsed,
            )
        )
    return batches


def aggregate_stream(
    messages: Iterator[Message],
    *,
    config: AggregatorConfig,
) -> Iterator[AggregatedBatch]:
    """Streaming version of aggregate (yields batches on completion)."""
    pending: dict[str, list[Message]] = defaultdict(list)
    first_seen: dict[str, float] = {}
    key_fn = config.correlation_key

    for msg in messages:
        if msg.timestamp == 0.0:
            msg.timestamp = time.time()
        key = _key_of(msg, key_fn)
        pending[key].append(msg)
        first_seen.setdefault(key, msg.timestamp)

        is_complete = False
        elapsed = msg.timestamp - first_seen[key]
        if (
            config.completion_size is not None
            and len(pending[key]) >= config.completion_size
        ):
            is_complete = True
        if (
            config.completion_timeout is not None
            and elapsed >= config.completion_timeout
        ):
            is_complete = True
        if is_complete:
            msgs = pending.pop(key)
            first_seen.pop(key, None)
            result = _combine(msgs, config.completion_strategy, config.custom_reducer)
            yield AggregatedBatch(
                key=key, result=result, size=len(msgs), elapsed=elapsed,
            )
