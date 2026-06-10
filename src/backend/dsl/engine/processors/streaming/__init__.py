"""Streaming processors package (S53 W2 decomp from streaming.py 737 LOC).

13 classes split into 4 groups:
- ``windows.py`` (5): _BaseWindow, TumblingWindowProcessor, SlidingWindowProcessor, SessionWindowProcessor, GroupByKeyProcessor
- ``message_meta.py`` (3): MessageExpirationProcessor, CorrelationIdProcessor, SchemaRegistryValidator
- ``reliability.py`` (3): ReplyToProcessor, ExactlyOnceProcessor, DurableSubscriberProcessor
- ``operations.py`` (2): ChannelPurgerProcessor, SamplingProcessor

Backward-compat: ``from src.backend.dsl.engine.processors.streaming import X`` works для всех 13 классов.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.streaming.message_meta import (  # S53 W2
    CorrelationIdProcessor,
    MessageExpirationProcessor,
    SchemaRegistryValidator,
)
from src.backend.dsl.engine.processors.streaming.operations import (  # S53 W2
    ChannelPurgerProcessor,
    SamplingProcessor,
)
from src.backend.dsl.engine.processors.streaming.reliability import (  # S53 W2
    DurableSubscriberProcessor,
    ExactlyOnceProcessor,
    ReplyToProcessor,
)
from src.backend.dsl.engine.processors.streaming.windows import (  # S53 W2
    GroupByKeyProcessor,
    SessionWindowProcessor,
    SlidingWindowProcessor,
    TumblingWindowProcessor,
    _BaseWindow,
)

__all__ = (
    "ChannelPurgerProcessor",
    "CorrelationIdProcessor",
    "DurableSubscriberProcessor",
    "ExactlyOnceProcessor",
    "GroupByKeyProcessor",
    "MessageExpirationProcessor",
    "ReplyToProcessor",
    "SamplingProcessor",
    "SchemaRegistryValidator",
    "SessionWindowProcessor",
    "SlidingWindowProcessor",
    "TumblingWindowProcessor",
    "_BaseWindow",
)
