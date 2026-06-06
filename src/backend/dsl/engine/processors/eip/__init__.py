"""Apache Camel EIP processors — re-export from submodules."""

from src.backend.dsl.engine.processors.eip.collection import (
    CollectProcessor,
    DiffProcessor,
    FindAllProcessor,
    FlattenProcessor,
    GroupByProcessor,
    IntersectProcessor,
    MaxByProcessor,
    MinByProcessor,
    OrElseProcessor,
    PartitionProcessor,
    SortByProcessor,
    SumByProcessor,
    UniqueProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control import (
    AggregatorProcessor,
    DelayProcessor,
    ForEachProcessor,
    LoopProcessor,
    OnCompletionProcessor,
    ThrottlerProcessor,
    WireTapProcessor,
)
from src.backend.dsl.engine.processors.eip.idempotency import (
    IdempotentConsumerProcessor,
)
from src.backend.dsl.engine.processors.eip.resilience import (
    CircuitBreakerProcessor,
    DeadLetterProcessor,
    FallbackChainProcessor,
    TimeoutProcessor,
)
from src.backend.dsl.engine.processors.eip.routing import (
    DynamicRouterProcessor,
    LoadBalancerProcessor,
    MulticastProcessor,
    MulticastRoutesProcessor,
    RecipientListProcessor,
    ScatterGatherProcessor,
)
from src.backend.dsl.engine.processors.eip.routing_slip import (
    ProcessorRegistry,
    RoutingSlipProcessor,
    SimpleRegistry,
)
from src.backend.dsl.engine.processors.eip.sequencing import ResequencerProcessor
from src.backend.dsl.engine.processors.eip.transformation import (
    ClaimCheckProcessor,
    MessageTranslatorProcessor,
    NormalizerProcessor,
    SortProcessor,
    SplitterProcessor,
)
from src.backend.dsl.engine.processors.eip.windowed_dedup import (
    WindowedCollectProcessor,
    WindowedDedupProcessor,
)

__all__ = (
    "AggregatorProcessor",
    "CircuitBreakerProcessor",
    "ClaimCheckProcessor",
    "CollectProcessor",
    "DeadLetterProcessor",
    "DelayProcessor",
    "DiffProcessor",
    "DynamicRouterProcessor",
    "FallbackChainProcessor",
    "FindAllProcessor",
    "FlattenProcessor",
    "ForEachProcessor",
    "GroupByProcessor",
    "IdempotentConsumerProcessor",
    "IntersectProcessor",
    "LoadBalancerProcessor",
    "LoopProcessor",
    "MaxByProcessor",
    "MessageTranslatorProcessor",
    "MinByProcessor",
    "MulticastProcessor",
    "MulticastRoutesProcessor",
    "NormalizerProcessor",
    "OnCompletionProcessor",
    "OrElseProcessor",
    "PartitionProcessor",
    "ProcessorRegistry",
    "RecipientListProcessor",
    "ResequencerProcessor",
    "RoutingSlipProcessor",
    "ScatterGatherProcessor",
    "SimpleRegistry",
    "SortByProcessor",
    "SortProcessor",
    "SplitterProcessor",
    "SumByProcessor",
    "ThrottlerProcessor",
    "TimeoutProcessor",
    "UniqueProcessor",
    "WindowedCollectProcessor",
    "WindowedDedupProcessor",
    "WireTapProcessor",
)
