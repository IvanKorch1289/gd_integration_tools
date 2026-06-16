"""S67 W1 - helpers.py part of backpressure decomp.

Module-level helpers (singleton access).

Functions: get_streaming_controller.
"""

from __future__ import annotations

from src.backend.core.resilience.backpressure.controller import (
    StreamingBackpressureController,
)

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

_controller_instance: StreamingBackpressureController | None = None


def get_streaming_controller() -> StreamingBackpressureController:
    """Singleton — один экземпляр StreamingBackpressureController."""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = StreamingBackpressureController()
    return _controller_instance
