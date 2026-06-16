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

from src.backend.core.resilience.backpressure.bulkhead import (
    AdaptiveBulkhead,  # S67 W1: re-export
)
from src.backend.core.resilience.backpressure.controller import (
    StreamingBackpressureController,  # S67 W1: re-export
)
from src.backend.core.resilience.backpressure.helpers import (
    get_streaming_controller,  # S67 W1: helper re-export
)
from src.backend.core.resilience.backpressure.stream_reader import (
    AdaptiveStreamReader,  # S67 W1: re-export
)
from src.backend.core.resilience.backpressure.types import (
    BackpressureState,  # S67 W1: re-export
    ConsumerControlProtocol,  # S67 W1: re-export
)

__all__ = (
    "ConsumerControlProtocol",
    "BackpressureState",
    "StreamingBackpressureController",
    "AdaptiveStreamReader",
    "AdaptiveBulkhead",
    "get_streaming_controller",
)
