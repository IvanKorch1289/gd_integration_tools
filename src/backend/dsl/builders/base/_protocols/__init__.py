"""RouteBuilder Protocol-контракты (S3-3 / M2-#21, W9 P2-13 split).

Cycle 30 P4-#4: Protocol interfaces documenting RouteBuilder contract.
These are NOT the composition refactor (which would break 200+ tests
and require multi-week migration), but they document the public API
surface that a future CompositionRouteBuilder must satisfy.

Migration path (per Master Prompt P4-#4):
1. Protocol definitions (this commit) -- documents contract.
2. CompositionRouteBuilder alongside RouteBuilder -- parallel impl.
3. Gradual migration of callers from RouteBuilder to CompositionRouteBuilder.
4. Eventually RouteBuilder becomes a thin wrapper or is removed.

S3-3 (ledger): вынесены из ``__init__.py`` (1422 LOC god-module) — протоколы
~1080 LOC чистой декларации без логики. ``__init__`` ре-экспортирует все
имена (back-compat: cycle_31 тесты импортируют их из ``base``).

W9 P2-13 (ADR-0320): _protocols.py (1094 LOC) → _protocols/ package с 6 family
sub-modules:
- _core.py (foundational contracts)
- _data.py (entity CRUD / batch / SQL / templates)
- _flow.py (control-flow / concurrency / time-resilience)
- _integration.py (proxy / sinks / sources / dispatch)
- _ai.py (LLM/RAG / Temporal / agent DSL)
- _support.py (converters / EIP content / collection / security / config)

Cycle 244: 21 Protocol classes + _shares_prefix helper. Каждый Protocol
структурно (typing.Protocol) описывает 5-15 cohesive-методов из одного
mixin/категории, чтобы:
1) downstream code мог type-check против ``RouteBuilder`` через ``isinstance``
   (runtime_checkable);
2) документация категоризирует 76 mixin-методов для IDE/help;
3) CompositionRouteBuilder (master prompt P4-#4 migration path) имеет
   explicit surface для постепенного внедрения.

Convention: имя ``_<Категория>_Protocol``, ``@_runtime_checkable``, docstring
one-liner, минимально-валидные сигнатуры (return Any для fluent-chain).
"""

from __future__ import annotations

from src.backend.dsl.builders.base._protocols._ai import (
    _RouteAgentProtocol as _RouteAgentProtocol,
)
from src.backend.dsl.builders.base._protocols._ai import (
    _RouteAIOpsProtocol as _RouteAIOpsProtocol,
)
from src.backend.dsl.builders.base._protocols._ai import (
    _RouteWorkflowOpsProtocol as _RouteWorkflowOpsProtocol,
)
from src.backend.dsl.builders.base._protocols._core import _RouteCore as _RouteCore
from src.backend.dsl.builders.base._protocols._core import (
    _RouteProcessorSteps as _RouteProcessorSteps,
)
from src.backend.dsl.builders.base._protocols._core import (
    _shares_prefix as _shares_prefix,
)
from src.backend.dsl.builders.base._protocols._data import (
    _RouteBatchDataProtocol as _RouteBatchDataProtocol,
)
from src.backend.dsl.builders.base._protocols._data import (
    _RouteDbProtocol as _RouteDbProtocol,
)
from src.backend.dsl.builders.base._protocols._data import (
    _RouteEntityCrudProtocol as _RouteEntityCrudProtocol,
)
from src.backend.dsl.builders.base._protocols._data import (
    _RoutePersistenceProtocol as _RoutePersistenceProtocol,
)
from src.backend.dsl.builders.base._protocols._data import (
    _RouteTemplateProtocol as _RouteTemplateProtocol,
)
from src.backend.dsl.builders.base._protocols._flow import (
    _RouteConcurrencyProtocol as _RouteConcurrencyProtocol,
)
from src.backend.dsl.builders.base._protocols._flow import (
    _RouteControlFlowProtocol as _RouteControlFlowProtocol,
)
from src.backend.dsl.builders.base._protocols._flow import (
    _RouteTimeResilienceProtocol as _RouteTimeResilienceProtocol,
)
from src.backend.dsl.builders.base._protocols._integration import (
    _RouteIntegrationCoreProtocol as _RouteIntegrationCoreProtocol,
)
from src.backend.dsl.builders.base._protocols._integration import (
    _RouteProxyProtocol as _RouteProxyProtocol,
)
from src.backend.dsl.builders.base._protocols._integration import (
    _RouteSinkProtocol as _RouteSinkProtocol,
)
from src.backend.dsl.builders.base._protocols._integration import (
    _RouteSourceProtocol as _RouteSourceProtocol,
)
from src.backend.dsl.builders.base._protocols._support import (
    _RouteCollectionProtocol as _RouteCollectionProtocol,
)
from src.backend.dsl.builders.base._protocols._support import (
    _RouteConfigProtocol as _RouteConfigProtocol,
)
from src.backend.dsl.builders.base._protocols._support import (
    _RouteContentProtocol as _RouteContentProtocol,
)
from src.backend.dsl.builders.base._protocols._support import (
    _RouteConverterProtocol as _RouteConverterProtocol,
)
from src.backend.dsl.builders.base._protocols._support import (
    _RouteSecurityProtocol as _RouteSecurityProtocol,
)

__all__ = [
    "_RouteAgentProtocol",
    "_RouteAIOpsProtocol",
    "_RouteBatchDataProtocol",
    "_RouteCollectionProtocol",
    "_RouteConcurrencyProtocol",
    "_RouteConfigProtocol",
    "_RouteContentProtocol",
    "_RouteConverterProtocol",
    "_RouteCore",
    "_RouteDbProtocol",
    "_RouteEntityCrudProtocol",
    "_RouteIntegrationCoreProtocol",
    "_RoutePersistenceProtocol",
    "_RouteProcessorSteps",
    "_RouteProxyProtocol",
    "_RouteSecurityProtocol",
    "_RouteSinkProtocol",
    "_RouteSourceProtocol",
    "_RouteTemplateProtocol",
    "_RouteTimeResilienceProtocol",
    "_RouteWorkflowOpsProtocol",
    "_shares_prefix",
]
