"""Apache Camel EIP processors — re-export from submodules."""

from src.backend.dsl.engine.processors.eip.collection import (  # noqa: F401 — re-export
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
from src.backend.dsl.engine.processors.eip.content_enricher import (  # noqa: F401 — re-export
    EnrichProcessor as EnrichProcessor,
)
from src.backend.dsl.engine.processors.eip.dict_ops import (  # noqa: F401 — re-export
    PydashGetProcessor,
    PydashMergeProcessor,
    PydashOmitProcessor,
    PydashPickProcessor,
    PydashSetProcessor,
)
from src.backend.dsl.engine.processors.eip.event_message import (  # noqa: F401 — re-export
    EventMessageEnvelope,
    EventMessageProcessor,
)
from src.backend.dsl.engine.processors.eip.filter_router_sampling import (  # noqa: F401 — re-export
    ContentBasedRouter,
    SamplingProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control import (  # noqa: F401 — re-export
    AggregatorProcessor,
    DelayProcessor,
    ForEachProcessor,
    LoopProcessor,
    OnCompletionProcessor,
    SensorProcessor,
    ThrottlerProcessor,
    WireTapProcessor,
)
from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor
from src.backend.dsl.engine.processors.eip.glom_ops import (  # noqa: F401 — re-export
    GlomExtractProcessor,
    GlomFlattenProcessor,
    GlomTransformProcessor,
)
from src.backend.dsl.engine.processors.eip.idempotency import (  # noqa: F401 — re-export
    IdempotentConsumerProcessor,
)
from src.backend.dsl.engine.processors.eip.marshal import (  # noqa: F401 — re-export
    CsvDataFormat,
    DataFormat,
    JsonDataFormat,
    MarshalProcessor,
    MessagePackDataFormat,
    PickleDataFormat,
    UnmarshalProcessor,
    XmlDataFormat,
)
from src.backend.dsl.engine.processors.eip.pipes_and_filters import (  # noqa: F401 — re-export
    PipesAndFiltersProcessor,
)
from src.backend.dsl.engine.processors.eip.reliability import (  # noqa: F401 — re-export
    CorrelationIdentifierProcessor,
    MessageExpirationProcessor,
    RedeliveryPolicyProcessor,
    ReturnAddressProcessor,
)
from src.backend.dsl.engine.processors.eip.resilience import (  # noqa: F401 — re-export
    CircuitBreakerProcessor,
    DeadLetterProcessor,
    FallbackChainProcessor,
    TimeoutProcessor,
)
from src.backend.dsl.engine.processors.eip.routing import (  # noqa: F401 — re-export
    DynamicRouterProcessor,
    LoadBalancerProcessor,
    MulticastProcessor,
    MulticastRoutesProcessor,
    RecipientListProcessor,
    ScatterGatherProcessor,
)
from src.backend.dsl.engine.processors.eip.routing_slip import (  # noqa: F401 — re-export
    ProcessorRegistry,
    RoutingSlipProcessor,
    SimpleRegistry,
)
from src.backend.dsl.engine.processors.eip.sequencing import ResequencerProcessor
from src.backend.dsl.engine.processors.eip.transactional import (  # noqa: F401 — re-export
    ProcessManagerProcessor,
    TransactionalClientProcessor,
)
from src.backend.dsl.engine.processors.eip.transformation import (  # noqa: F401 — re-export
    ClaimCheckProcessor,
    MessageTranslatorProcessor,
    NormalizerProcessor,
    SortProcessor,
    SplitterProcessor,
)
from src.backend.dsl.engine.processors.eip.windowed_dedup import (  # noqa: F401 — re-export
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
    "EnrichProcessor",
    "DynamicRouterProcessor",
    "EventMessageEnvelope",
    "EventMessageProcessor",
    "FallbackChainProcessor",
    "FindAllProcessor",
    "FlattenProcessor",
    "ForEachProcessor",
    "ForkJoinProcessor",
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
    "ProcessManagerProcessor",
    "ProcessorRegistry",
    "PydashGetProcessor",
    "PydashMergeProcessor",
    "PydashOmitProcessor",
    "PydashPickProcessor",
    "PydashSetProcessor",
    "RecipientListProcessor",
    "RedeliveryPolicyProcessor",
    "ResequencerProcessor",
    "ReturnAddressProcessor",
    "RoutingSlipProcessor",
    "SamplingProcessor",
    "ScatterGatherProcessor",
    "SensorProcessor",
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
