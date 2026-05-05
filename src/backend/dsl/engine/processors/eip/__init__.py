"""Apache Camel EIP processors — re-export from submodules."""

from src.dsl.engine.processors.eip.flow_control import (
    AggregatorProcessor,
    DelayProcessor,
    LoopProcessor,
    OnCompletionProcessor,
    ThrottlerProcessor,
    WireTapProcessor,
)
from src.dsl.engine.processors.eip.idempotency import IdempotentConsumerProcessor
from src.dsl.engine.processors.eip.resilience import (
    CircuitBreakerProcessor,
    DeadLetterProcessor,
    FallbackChainProcessor,
    TimeoutProcessor,
)
from src.dsl.engine.processors.eip.routing import (
    DynamicRouterProcessor,
    LoadBalancerProcessor,
    MulticastProcessor,
    MulticastRoutesProcessor,
    RecipientListProcessor,
    ScatterGatherProcessor,
)
from src.dsl.engine.processors.eip.sequencing import ResequencerProcessor
from src.dsl.engine.processors.eip.transformation import (
    ClaimCheckProcessor,
    MessageTranslatorProcessor,
    NormalizerProcessor,
    SortProcessor,
    SplitterProcessor,
)
from src.dsl.engine.processors.eip.windowed_dedup import (
    WindowedCollectProcessor,
    WindowedDedupProcessor,
)

__all__ = (
    "AggregatorProcessor",
    "CircuitBreakerProcessor",
    "ClaimCheckProcessor",
    "DeadLetterProcessor",
    "DelayProcessor",
    "DynamicRouterProcessor",
    "FallbackChainProcessor",
    "IdempotentConsumerProcessor",
    "LoadBalancerProcessor",
    "LoopProcessor",
    "MessageTranslatorProcessor",
    "MulticastProcessor",
    "MulticastRoutesProcessor",
    "NormalizerProcessor",
    "OnCompletionProcessor",
    "RecipientListProcessor",
    "ResequencerProcessor",
    "ScatterGatherProcessor",
    "SortProcessor",
    "SplitterProcessor",
    "ThrottlerProcessor",
    "TimeoutProcessor",
    "WindowedCollectProcessor",
    "WindowedDedupProcessor",
    "WireTapProcessor",
)
