from __future__ import annotations

"""EIP routing processors package (S63 W2 decomp from routing.py 496 LOC).

6 processor classes decomposed в 5 files (per routing pattern):
- ``dynamic.py``: DynamicRouterProcessor
- ``scatter_gather.py``: ScatterGatherProcessor
- ``recipient_list.py``: RecipientListProcessor
- ``load_balancer.py``: LoadBalancerProcessor
- ``multicast.py``: MulticastProcessor, MulticastRoutesProcessor

Backward-compat: ``from src.backend.dsl.engine.processors.eip.routing import DynamicRouterProcessor`` works.
"""


from src.backend.dsl.engine.processors.eip.routing.dynamic import (
    DynamicRouterProcessor,  # S63 W2: re-export
)
from src.backend.dsl.engine.processors.eip.routing.load_balancer import (
    LoadBalancerProcessor,  # S63 W2: re-export
)
from src.backend.dsl.engine.processors.eip.routing.multicast import (
    MulticastProcessor,  # S63 W2: re-export
    MulticastRoutesProcessor,  # S63 W2: re-export
)
from src.backend.dsl.engine.processors.eip.routing.recipient_list import (
    RecipientListProcessor,  # S63 W2: re-export
)
from src.backend.dsl.engine.processors.eip.routing.scatter_gather import (
    ScatterGatherProcessor,  # S63 W2: re-export
)

__all__ = (
    "DynamicRouterProcessor",
    "ScatterGatherProcessor",
    "RecipientListProcessor",
    "LoadBalancerProcessor",
    "MulticastProcessor",
    "MulticastRoutesProcessor",
)
