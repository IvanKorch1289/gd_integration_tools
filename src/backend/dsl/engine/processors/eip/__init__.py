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
from src.backend.dsl.engine.processors.eip.dict_ops import (
    PydashGetProcessor,
    PydashMergeProcessor,
    PydashOmitProcessor,
    PydashPickProcessor,
    PydashSetProcessor,
)
from src.backend.dsl.engine.processors.eip.event_message import (
    EventMessageEnvelope,
    EventMessageProcessor,
)
from src.backend.dsl.engine.processors.eip.filter_router_sampling import (
    ContentBasedRouter,
    SamplingProcessor,
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
from src.backend.dsl.engine.processors.eip.glom_ops import (
    GlomExtractProcessor,
    GlomFlattenProcessor,
    GlomTransformProcessor,
)
from src.backend.dsl.engine.processors.eip.idempotency import (
    IdempotentConsumerProcessor,
)
from src.backend.dsl.engine.processors.eip.marshal import (
    CsvDataFormat,
    DataFormat,
    JsonDataFormat,
    MarshalProcessor,
    MessagePackDataFormat,
    PickleDataFormat,
    UnmarshalProcessor,
    XmlDataFormat,
)
from src.backend.dsl.engine.processors.eip.pipes_and_filters import (
    PipesAndFiltersProcessor,
)
from src.backend.dsl.engine.processors.eip.reliability import (
    CorrelationIdentifierProcessor,
    MessageExpirationProcessor,
    RedeliveryPolicyProcessor,
    ReturnAddressProcessor,
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
from src.backend.dsl.engine.processors.eip.transactional import (
    ProcessManagerProcessor,
    TransactionalClientProcessor,
)
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
    "ContentBasedRouter",
    "CorrelationIdentifierProcessor",
    "CsvDataFormat",
    "DataFormat",
    "DeadLetterProcessor",
    "DelayProcessor",
    "DiffProcessor",
    "DynamicRouterProcessor",
    "EventMessageEnvelope",
    "EventMessageProcessor",
    "FallbackChainProcessor",
    "FindAllProcessor",
    "FlattenProcessor",
    "ForEachProcessor",
    "GlomExtractProcessor",
    "GlomFlattenProcessor",
    "GlomTransformProcessor",
    "GroupByProcessor",
    "IdempotentConsumerProcessor",
    "IntersectProcessor",
    "JsonDataFormat",
    "LoadBalancerProcessor",
    "LoopProcessor",
    "MarshalProcessor",
    "MaxByProcessor",
    "MessageExpirationProcessor",
    "MessagePackDataFormat",
    "MessageTranslatorProcessor",
    "MinByProcessor",
    "MulticastProcessor",
    "MulticastRoutesProcessor",
    "NormalizerProcessor",
    "OnCompletionProcessor",
    "OrElseProcessor",
    "PartitionProcessor",
    "PickleDataFormat",
    "PipesAndFiltersProcessor",
    "ProcessorRegistry",
    "PydashGetProcessor",
    "PydashMergeProcessor",
    "PydashOmitProcessor",
    "PydashPickProcessor",
    "PydashSetProcessor",
    "ProcessManagerProcessor",
    "RecipientListProcessor",
    "RedeliveryPolicyProcessor",
    "ResequencerProcessor",
    "ReturnAddressProcessor",
    "RoutingSlipProcessor",
    "SamplingProcessor",
    "ScatterGatherProcessor",
    "SimpleRegistry",
    "SortByProcessor",
    "SortProcessor",
    "SplitterProcessor",
    "SumByProcessor",
    "ThrottlerProcessor",
    "TimeoutProcessor",
    "TransactionalClientProcessor",
    "UniqueProcessor",
    "UnmarshalProcessor",
    "WindowedCollectProcessor",
    "WindowedDedupProcessor",
    "WireTapProcessor",
    "XmlDataFormat",
)
