from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from src.backend.core.logging import get_logger

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

def get_streaming_controller() -> StreamingBackpressureController:
    """Singleton — один экземпляр StreamingBackpressureController."""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = StreamingBackpressureController()
    return _controller_instance

