"""In-flight request registry (S91 M5-#2 helper).

Простой singleton counter для graceful shutdown coordination.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _InflightCounter:
    """Thread-safe counter (asyncio.Lock не нужен — GIL защищает int ops)."""
    value: int = 0


_INFLIGHT_COUNTER = _InflightCounter()
