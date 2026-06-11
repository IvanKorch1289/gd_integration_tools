from __future__ import annotations

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


def get_streaming_controller() -> StreamingBackpressureController:
    """Singleton — один экземпляр StreamingBackpressureController."""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = StreamingBackpressureController()
    return _controller_instance
