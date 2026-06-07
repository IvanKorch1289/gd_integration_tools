"""Aiocache proof-of-concept (S59 W4).

Демонстрирует использование ``aiocache`` library в проектном контексте.
НЕ production-готовый wrapper — это просто proof что библиотека работает
в async stack проекта (FastAPI + asyncio + Redis).

**Scope S59 W4** (honest):
* Inventory + ADR-0086 (full migration plan);
* POC: 1 функция, декорированная ``@aiocache.cached``;
* Tests: prove aiocache работает в pytest-async среде проекта.

**Full migration** (S60+):
* 1778 LOC custom cache → aiocache (не 1:1, требует feature-by-feature
  evaluation — см. ADR-0086).
"""
from __future__ import annotations

from typing import Any

import aiocache

__all__ = ("fetch_with_aiocache",)


@aiocache.cached(ttl=60, namespace="s59w4_poc", key_builder=None)  # type: ignore[misc]
async def fetch_with_aiocache(key: str) -> dict[str, Any]:
    """Демо async function, кэшируемая через aiocache.

    Args:
        key: Cache key.

    Returns:
        Dict с timestamp + echo для проверки cache hit/miss.
    """
    import time

    return {
        "key": key,
        "fetched_at": time.time(),
        "result": f"computed_for_{key}",
    }
