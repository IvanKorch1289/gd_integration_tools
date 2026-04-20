"""Message Replay Service — запись и воспроизведение inbound сообщений.

Снижает MTTR: все inbound сообщения (webhook/MQTT/email/gRPC)
записываются с raw payload. При сбое — replay через UI или API.

Actions: replay.list, replay.one, replay.bulk, replay.stats
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


__all__ = ("MessageReplayService", "ReplayMessage", "ReplayStatus", "get_replay_service")

logger = logging.getLogger(__name__)


class ReplayStatus(str, Enum):
    STORED = "stored"
    REPLAYED = "replayed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class ReplayMessage:
    id: str = field(default_factory=lambda: uuid4().hex[:16])
    source: str = ""
    action: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, Any] = field(default_factory=dict)
    status: ReplayStatus = ReplayStatus.STORED
    error: str | None = None
    timestamp: float = field(default_factory=time.time)
    replay_count: int = 0


class MessageReplayService:
    """Записывает все inbound сообщения и позволяет replay."""

    def __init__(self, max_history: int = 10000) -> None:
        self._messages: dict[str, ReplayMessage] = {}
        self._max_history = max_history

    async def record(
        self,
        source: str,
        action: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
    ) -> str:
        """Записывает inbound сообщение. Возвращает message_id."""
        msg = ReplayMessage(
            source=source, action=action,
            payload=payload, headers=headers or {},
        )
        self._messages[msg.id] = msg
        self._trim()
        return msg.id

    async def list_messages(
        self,
        status: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Возвращает список сообщений с фильтрацией."""
        msgs = list(self._messages.values())
        if status:
            msgs = [m for m in msgs if m.status.value == status]
        if source:
            msgs = [m for m in msgs if m.source == source]
        msgs.sort(key=lambda m: m.timestamp, reverse=True)
        total = len(msgs)
        page = msgs[offset:offset + limit]
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "messages": [self._to_dict(m) for m in page],
        }

    async def replay_one(self, message_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Воспроизводит одно сообщение."""
        msg = self._messages.get(message_id)
        if msg is None:
            return {"status": "not_found", "id": message_id}

        if dry_run:
            return {"status": "dry_run", "id": message_id, "action": msg.action, "payload": msg.payload}

        try:
            from app.dsl.commands.registry import action_handler_registry
            from app.schemas.invocation import ActionCommandSchema

            command = ActionCommandSchema(
                action=msg.action,
                payload=msg.payload,
                meta={"source": f"replay:{msg.source}", "replay_of": msg.id},
            )
            result = await action_handler_registry.dispatch(command)
            msg.status = ReplayStatus.REPLAYED
            msg.replay_count += 1
            return {"status": "replayed", "id": msg.id, "result": result}
        except Exception as exc:
            msg.status = ReplayStatus.FAILED
            msg.error = str(exc)
            logger.error("Replay failed for %s: %s", message_id, exc)
            return {"status": "error", "id": msg.id, "message": str(exc)}

    async def replay_bulk(
        self, message_ids: list[str] | None = None, status_filter: str = "stored",
    ) -> dict[str, Any]:
        """Массовый replay сообщений."""
        if message_ids:
            targets = [self._messages[mid] for mid in message_ids if mid in self._messages]
        else:
            targets = [m for m in self._messages.values() if m.status.value == status_filter]

        results = []
        for msg in targets:
            r = await self.replay_one(msg.id)
            results.append(r)

        replayed = sum(1 for r in results if r.get("status") == "replayed")
        return {"total": len(targets), "replayed": replayed, "results": results}

    async def stats(self) -> dict[str, Any]:
        """Статистика по сохранённым сообщениям."""
        msgs = list(self._messages.values())
        by_status: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for m in msgs:
            by_status[m.status.value] = by_status.get(m.status.value, 0) + 1
            by_source[m.source] = by_source.get(m.source, 0) + 1
        return {"total": len(msgs), "by_status": by_status, "by_source": by_source}

    def _trim(self) -> None:
        while len(self._messages) > self._max_history:
            oldest_key = min(self._messages, key=lambda k: self._messages[k].timestamp)
            del self._messages[oldest_key]

    @staticmethod
    def _to_dict(msg: ReplayMessage) -> dict[str, Any]:
        return {
            "id": msg.id, "source": msg.source, "action": msg.action,
            "status": msg.status.value, "error": msg.error,
            "timestamp": msg.timestamp, "replay_count": msg.replay_count,
            "payload_preview": str(msg.payload)[:200],
        }


_replay_service_instance = MessageReplayService()


def get_replay_service() -> MessageReplayService:
    return _replay_service_instance
