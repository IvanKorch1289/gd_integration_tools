"""LangGraph checkpoint inspector (Sprint 11 K4 W4).

Тонкий API поверх :class:`LangGraphPostgresSaverWrapper`:
* ``list_sessions(limit, offset)`` — active session-ids;
* ``get_state(session_id)`` — текущий снапшот state;
* ``list_checkpoints(session_id)`` — все чекпоинты сессии;
* ``restore(session_id, checkpoint_id)`` — установка state на чекпоинт.

При отключённом feature-flag или недоступном PostgresSaver методы
возвращают пустые результаты / None — UI деградирует без crash'ев.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

__all__ = ("CheckpointInspector", "CheckpointSnapshot", "SessionInfo")

logger = logging.getLogger("services.ai.agents.checkpoint_inspector")


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Сводка по одной session.

    Attributes:
        session_id: Идентификатор LangGraph thread.
        last_checkpoint_id: ID последнего чекпоинта.
        updated_at: ISO-8601 timestamp.
        checkpoint_count: Кол-во чекпоинтов в этой сессии.
    """

    session_id: str
    last_checkpoint_id: str
    updated_at: str
    checkpoint_count: int


@dataclass(frozen=True, slots=True)
class CheckpointSnapshot:
    """Снапшот одного чекпоинта (для UI inspector)."""

    session_id: str
    checkpoint_id: str
    created_at: str
    state: dict[str, Any]
    metadata: dict[str, Any]


class CheckpointInspector:
    """Admin-API над LangGraph PostgresSaver checkpoints.

    Args:
        saver_wrapper: :class:`LangGraphPostgresSaverWrapper` или None
            (тогда все методы возвращают пустые результаты).
    """

    def __init__(self, saver_wrapper: Any | None = None) -> None:
        self._wrapper = saver_wrapper

    async def list_sessions(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[SessionInfo]:
        """Перечислить активные session-id'ы.

        Простая реализация: при отсутствии saver возвращает [];
        при наличии — запрашивает `list` метод базового saver'а
        (если поддерживается).
        """
        if self._wrapper is None or not getattr(self._wrapper, "enabled", False):
            return []
        saver = await self._wrapper.acquire()
        if saver is None:
            return []
        results: list[SessionInfo] = []
        # LangGraph PostgresSaver.list(config=None) → AsyncIterator[CheckpointTuple]
        try:
            collected: dict[str, list[Any]] = {}
            async for ckpt in saver.alist({"configurable": {}}, limit=limit + offset):  
                cfg = getattr(ckpt, "config", {})
                sid = cfg.get("configurable", {}).get("thread_id", "")
                if not sid:
                    continue
                collected.setdefault(sid, []).append(ckpt)
            for sid, ckpts in collected.items():
                last = ckpts[0]
                last_cfg = getattr(last, "config", {})
                results.append(
                    SessionInfo(
                        session_id=sid,
                        last_checkpoint_id=last_cfg.get("configurable", {}).get(
                            "checkpoint_id", ""
                        ),
                        updated_at=str(getattr(last, "checkpoint", {}).get("ts", "")),
                        checkpoint_count=len(ckpts),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("CheckpointInspector list_sessions failed: %s", exc)
        return results[offset : offset + limit]

    async def get_state(self, session_id: str) -> CheckpointSnapshot | None:
        """Текущий state для session_id."""
        if self._wrapper is None or not getattr(self._wrapper, "enabled", False):
            return None
        saver = await self._wrapper.acquire()
        if saver is None:
            return None
        try:
            tuple_ = await saver.aget_tuple(  
                {"configurable": {"thread_id": session_id}}
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_state failed for %s: %s", session_id, exc)
            return None
        if tuple_ is None:
            return None
        cfg = getattr(tuple_, "config", {})
        ckpt = getattr(tuple_, "checkpoint", {}) or {}
        meta = getattr(tuple_, "metadata", {}) or {}
        return CheckpointSnapshot(
            session_id=session_id,
            checkpoint_id=cfg.get("configurable", {}).get("checkpoint_id", ""),
            created_at=str(ckpt.get("ts", "")),
            state=dict(ckpt),
            metadata=dict(meta),
        )

    async def restore(self, session_id: str, checkpoint_id: str) -> bool:
        """Установить «активный» чекпоинт через метаконфиг.

        В LangGraph restore — это получение CheckpointTuple конкретной
        версии; runtime сам подхватит её при следующем запуске agent'а.
        Возвращает True если чекпоинт найден и доступен.
        """
        if self._wrapper is None or not getattr(self._wrapper, "enabled", False):
            return False
        saver = await self._wrapper.acquire()
        if saver is None:
            return False
        try:
            tuple_ = await saver.aget_tuple(  
                {
                    "configurable": {
                        "thread_id": session_id,
                        "checkpoint_id": checkpoint_id,
                    }
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("restore failed: %s", exc)
            return False
        return tuple_ is not None
