"""S175: eip/flow_control subpackage — split 433 LOC god-file.

Phase 2 done: все 7 классов вынесены в отдельные файлы.

Modules:
- :mod:`wire_tap` — :class:`WireTapProcessor`
- :mod:`throttler` — :class:`ThrottlerProcessor`
- :mod:`delay` — :class:`DelayProcessor`
- :mod:`aggregator` — :class:`AggregatorProcessor`
- :mod:`loop` — :class:`LoopProcessor`
- :mod:`foreach` — :class:`ForEachProcessor`
- :mod:`oncompletion` — :class:`OnCompletionProcessor`
- :mod:`_legacy` — backward-compat stub (S175 Phase 1)
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.eip.flow_control.aggregator import (  # noqa: F401
    AggregatorProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control.delay import (  # noqa: F401
    DelayProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control.foreach import (  # noqa: F401
    ForEachProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control.loop import (  # noqa: F401
    LoopProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control.oncompletion import (  # noqa: F401
    OnCompletionProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control.throttler import (  # noqa: F401
    ThrottlerProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control.wire_tap import (  # noqa: F401
    WireTapProcessor,
)

__all__ = (
    "AggregatorProcessor",
    "DelayProcessor",
    "ForEachProcessor",
    "LoopProcessor",
    "OnCompletionProcessor",
    "ThrottlerProcessor",
    "WireTapProcessor",
)
