"""Admin REST для LangGraph checkpoint UI (Sprint 11 K4 W4).

* ``GET /admin/langgraph/checkpoints`` — список сессий с last-checkpoint.
* ``GET /admin/langgraph/checkpoints/{session_id}`` — state по сессии.
* ``POST /admin/langgraph/checkpoints/{session_id}/restore`` —
  установка ``checkpoint_id`` как активного.

Эндпоинты доступны только при ``feature_flags.langgraph_checkpoint_ui=True``.
Auth = admin-only (через существующий require_admin guard).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from src.backend.core.config.features import feature_flags

router = APIRouter(prefix="/admin/langgraph", tags=["admin", "langgraph"])


def _guard_enabled() -> None:
    if not feature_flags.langgraph_checkpoint_ui:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="langgraph_checkpoint_ui feature disabled",
        )


async def _inspector() -> Any:
    from src.backend.services.ai.agents.checkpoint_inspector import CheckpointInspector
    from src.backend.services.ai.agents.langgraph_postgres_saver import (
        get_langgraph_postgres_saver,
    )

    saver = await get_langgraph_postgres_saver()
    return CheckpointInspector(saver_wrapper=saver)


@router.get("/checkpoints")
async def list_checkpoints(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Список активных LangGraph сессий с последним чекпоинтом."""
    _guard_enabled()
    inspector = await _inspector()
    sessions = await inspector.list_sessions(limit=limit, offset=offset)
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "last_checkpoint_id": s.last_checkpoint_id,
                "updated_at": s.updated_at,
                "checkpoint_count": s.checkpoint_count,
            }
            for s in sessions
        ],
        "count": len(sessions),
    }


@router.get("/checkpoints/{session_id}")
async def get_session_state(session_id: str) -> dict[str, Any]:
    """State одной сессии (текущий чекпоинт)."""
    _guard_enabled()
    inspector = await _inspector()
    snapshot = await inspector.get_state(session_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
        )
    return {
        "session_id": snapshot.session_id,
        "checkpoint_id": snapshot.checkpoint_id,
        "created_at": snapshot.created_at,
        "state": snapshot.state,
        "metadata": snapshot.metadata,
    }


@router.post("/checkpoints/{session_id}/restore")
async def restore_checkpoint(session_id: str, checkpoint_id: str) -> dict[str, Any]:
    """Установить активный чекпоинт сессии (time-travel)."""
    _guard_enabled()
    inspector = await _inspector()
    ok = await inspector.restore(session_id, checkpoint_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"checkpoint {checkpoint_id} not found for session {session_id}",
        )
    return {"restored": True, "session_id": session_id, "checkpoint_id": checkpoint_id}
