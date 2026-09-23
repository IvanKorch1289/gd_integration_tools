"""Backpressure + adaptive bulkhead package (S67 W1 decomp from backpressure.py 465 LOC).

5 classes + 1 func -> 5 files (per-concern):
- ``types.py``: ConsumerControlProtocol (interface) + BackpressureState (data)
- ``controller.py``: StreamingBackpressureController (main, 11 methods)
- ``stream_reader.py``: AdaptiveStreamReader (3 methods)
- ``bulkhead.py``: AdaptiveBulkhead (7 methods)
- ``helpers.py``: 1 module-level func

Backward-compat: ``from src.backend.core.resilience.backpressure import StreamingBackpressureController`` works.
"""

from __future__ import annotations

from src.backend.core.resilience.backpressure.bulkhead import (  # noqa: F401 — re-export
    AdaptiveBulkhead,  # S67 W1: re-export
)
from src.backend.core.resilience.backpressure.controller import (  # noqa: F401 — re-export
    StreamingBackpressureController,  # S67 W1: re-export
)
from src.backend.core.resilience.backpressure.helpers import (  # noqa: F401 — re-export
    get_streaming_controller,  # S67 W1: helper re-export
)
from src.backend.core.resilience.backpressure.stream_reader import (  # noqa: F401 — re-export
    AdaptiveStreamReader,  # S67 W1: re-export
)
from src.backend.core.resilience.backpressure.types import (  # noqa: F401 — re-export
    BackpressureState,  # S67 W1: re-export
    ConsumerControlProtocol,  # S67 W1: re-export
)

__all__ = (
    "AdaptiveBulkhead",
    "AdaptiveStreamReader",
    "BackpressureState",
    "ConsumerControlProtocol",
    "StreamingBackpressureController",
    "get_streaming_controller",
)
