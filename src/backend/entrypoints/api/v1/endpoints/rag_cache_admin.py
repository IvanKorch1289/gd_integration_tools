"""Admin-роутер для 3-tier RAG cache (К4 MVP, Шаг 7).

Эндпоинты для Streamlit-страницы ``74_Cache_Dashboard.py``:

* ``GET /admin/rag-cache/stats`` — снимок hit/miss-счётчиков по tier'ам.
* ``POST /admin/rag-cache/flush`` — полная очистка одного tier или всех.
* ``GET /admin/rag-cache/events`` — последние invalidate-события (in-memory ring).
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.backend.infrastructure.cache.rag.metrics import get_metrics_snapshot

__all__ = ("record_invalidation_event", "router")

router = APIRouter()

_EVENTS_RING: deque[dict[str, Any]] = deque(maxlen=200)


def record_invalidation_event(event: dict[str, Any]) -> None:
    """Записывает invalidate-событие в кольцевой буфер (для admin UI)."""
    _EVENTS_RING.append({"ts": datetime.now(UTC).isoformat(), **event})


def _get_three_tier_cache() -> Any:
    """Lazy-резолв ThreeTierRagCache из app.state (если зарегистрирован)."""
    try:
        from src.backend.core.di.app_state import get_app_ref

        app = get_app_ref()
    except Exception as _:
        return None
    if app is None:
        return None
    return getattr(app.state, "three_tier_rag_cache", None)


@router.get("/rag-cache/stats", summary="Снимок hit/miss по tier'ам RAG-кэша")
async def get_rag_cache_stats() -> dict[str, Any]:
    """Возвращает счётчики hits/misses по l1/l2/l3."""
    snapshot = get_metrics_snapshot()
    cache = _get_three_tier_cache()
    enabled: dict[str, bool] = {}
    if cache is not None:
        enabled = {
            "l1": getattr(cache, "_l1_enabled", False),
            "l2": getattr(cache, "_l2_enabled", False),
            "l3": getattr(cache, "_l3_enabled", False),
        }
    return {"counters": snapshot, "enabled": enabled}


@router.post("/rag-cache/flush", summary="Очистить tier RAG-кэша")
async def flush_rag_cache_tier(
    tier: str | None = Query(default=None, description="l1|l2|l3 или None для всех"),
) -> dict[str, Any]:
    """Полная очистка кэша по tier'у."""
    if tier and tier not in {"l1", "l2", "l3"}:
        raise HTTPException(status_code=400, detail="tier должен быть l1|l2|l3")
    cache = _get_three_tier_cache()
    if cache is None:
        raise HTTPException(
            status_code=503, detail="ThreeTierRagCache не зарегистрирован в app.state"
        )
    return {"flushed": await cache.flush(tier=tier)}


@router.get("/rag-cache/events", summary="Последние invalidate-события")
async def get_rag_invalidation_events(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Возвращает последние invalidate-события (FIFO-ring до 200)."""
    return list(_EVENTS_RING)[-limit:]
