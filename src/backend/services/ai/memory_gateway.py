"""Block 4.1 (gap-ai-4.1, ADR-0075): UnifiedMemoryGateway implementation.

Реализация :class:`AgentMemoryGateway` Protocol поверх двух existing services:

* :class:`AgentMemoryService` (MongoDB) — short-term: messages, scratchpad,
  key-value facts с TTL (1h / 30d).
* :class:`LangMemService` (Postgres + Qdrant) — long-term: episodic /
  procedural / semantic с embedding-based recall + ConsolidationEngine.

Все методы принимают ``tenant_id: str`` обязательно (kw-only). Tenant
изоляция реализуется через namespace-prefix в Mongo collection и
``session_id`` prefix в PG/Qdrant (full multi-tenant scoping — carryover
Block 4.2 + S21 RLS infrastructure).

Lazy-resolve dependencies: ``AgentMemoryService`` и ``LangMemService``
резолвятся через ``app_state_singleton`` → graceful behavior при отсутствии
одного из бэкендов (е.g. LangMem disabled = recall_semantic returns []).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.interfaces.agent_memory import (
    AgentMemoryGateway,
    MemoryFact,
    MemoryMessage,
)

__all__ = ("UnifiedMemoryGateway", "get_memory_gateway")

logger = logging.getLogger(__name__)


def _scope(tenant_id: str, session_id: str) -> str:
    """Возвращает namespaced session-id с tenant prefix.

    Все Mongo/Qdrant ключи должны быть ``<tenant_id>:<session_id>``
    чтобы один tenant не видел память другого даже при ошибке RLS-policy.
    """
    if not tenant_id:
        raise ValueError("tenant_id обязателен (multi-tenant isolation)")
    return f"{tenant_id}:{session_id}"


class UnifiedMemoryGateway(AgentMemoryGateway):
    """Block 4.1: dispatch short-term/long-term по типу операции.

    Args:
        short_term: :class:`AgentMemoryService` instance (Mongo backend).
        long_term: :class:`LangMemService` instance (PG + Qdrant) или None.
            При None — ``recall_semantic``/``save_fact`` graceful-degraded.

    Принципы:
        * tenant_id обязателен в каждом методе (ValueError при пустом).
        * conversation operations → short_term (Mongo TTL).
        * semantic operations → long_term (Qdrant с embedding).
        * consolidate триггерит long_term.consolidate() если доступен.
    """

    def __init__(self, *, short_term: Any, long_term: Any | None = None) -> None:
        self._short = short_term
        self._long = long_term

    async def get_messages(
        self, *, tenant_id: str, session_id: str, limit: int = 50
    ) -> list[MemoryMessage]:
        """Conversation history через ``AgentMemoryService.get_conversation``."""
        scoped = _scope(tenant_id, session_id)
        try:
            raw = await self._short.get_conversation(scoped, limit=limit)
        except Exception as exc:  # noqa: BLE001 — backend unavailable
            logger.warning("memory_gateway.get_messages_failed: %s", exc)
            return []
        return [
            MemoryMessage(
                role=str(m.get("role", "unknown")),
                content=str(m.get("content", "")),
                ts=float(m.get("ts", 0.0)),
                metadata=m.get("metadata") or {},
            )
            for m in (raw or [])
        ]

    async def save_message(
        self,
        *,
        tenant_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: Mapping[str, object] | None = None,
    ) -> str:
        """Append сообщение в conversation memory.

        Returns ``message_id`` (UUIDv4 — backend-agnostic).
        """
        scoped = _scope(tenant_id, session_id)
        message_id = str(uuid.uuid4())
        try:
            await self._short.add_message(
                scoped,
                role=role,
                content=content,
                metadata={**(dict(metadata) if metadata else {}), "id": message_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_gateway.save_message_failed: %s", exc)
        return message_id

    async def get_facts(
        self, *, tenant_id: str, session_id: str | None = None, limit: int = 50
    ) -> list[MemoryFact]:
        """Возвращает known facts.

        При ``session_id`` указан — short_term.get_facts (key-value); иначе
        long_term recall с пустым query (top_k=limit) — semantic facts
        tenant'а в целом.
        """
        if session_id is not None:
            scoped = _scope(tenant_id, session_id)
            try:
                fact_dict = await self._short.get_facts(scoped)
            except Exception as exc:  # noqa: BLE001
                logger.warning("memory_gateway.get_facts_short_failed: %s", exc)
                return []
            return [
                MemoryFact(
                    content=f"{k}={v}",
                    confidence=1.0,
                    source_session_id=session_id,
                    tags=("kv",),
                )
                for k, v in (fact_dict or {}).items()
            ]
        # Global для tenant: long-term recall если доступен.
        if self._long is None:
            return []
        try:
            results = await self._long.recall(
                tenant_id=tenant_id, query="", top_k=limit
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_gateway.get_facts_long_failed: %s", exc)
            return []
        return [_lang_to_fact(r) for r in (results or [])]

    async def save_fact(
        self,
        *,
        tenant_id: str,
        content: str,
        confidence: float = 1.0,
        source_session_id: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> str:
        """Записывает факт в long-term semantic store.

        При отсутствии :class:`LangMemService` — fallback в short_term как
        key-value (с auto-generated key=``fact_<uuid8>``).
        """
        if self._long is not None:
            try:
                fact_id = await self._long.add_semantic(
                    tenant_id=tenant_id,
                    content=content,
                    confidence=confidence,
                    source_session_id=source_session_id,
                    tags=list(tags),
                )
                return str(fact_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("memory_gateway.save_fact_long_failed: %s", exc)

        # Fallback на short_term key-value.
        fact_key = f"fact_{uuid.uuid4().hex[:8]}"
        session_scoped = _scope(tenant_id, source_session_id or "_global")
        try:
            await self._short.set_fact(session_scoped, fact_key, content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_gateway.save_fact_short_failed: %s", exc)
        return fact_key

    async def recall_semantic(
        self, *, tenant_id: str, query: str, top_k: int = 5
    ) -> list[MemoryFact]:
        """Semantic search через :class:`LangMemService.recall`."""
        if self._long is None:
            return []
        try:
            results = await self._long.recall(
                tenant_id=tenant_id, query=query, top_k=top_k
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_gateway.recall_failed: %s", exc)
            return []
        return [_lang_to_fact(r) for r in (results or [])]

    async def get_scratchpad(self, *, tenant_id: str, session_id: str) -> str | None:
        """Возвращает scratchpad сессии (короткая рабочая область агента)."""
        scoped = _scope(tenant_id, session_id)
        try:
            value = await self._short.get_scratchpad(scoped)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_gateway.get_scratchpad_failed: %s", exc)
            return None
        return value if value else None

    async def save_scratchpad(
        self, *, tenant_id: str, session_id: str, content: str
    ) -> None:
        """Записывает scratchpad (один документ на session)."""
        scoped = _scope(tenant_id, session_id)
        try:
            await self._short.set_scratchpad(scoped, content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_gateway.save_scratchpad_failed: %s", exc)

    async def consolidate(self, *, tenant_id: str, session_id: str) -> int:
        """Block 4.2: short-term → semantic consolidation.

        Triggers :class:`LangMemService.consolidate(session_id)` если доступен,
        иначе возвращает 0 (degraded — без long-term).
        """
        if self._long is None:
            return 0
        scoped = _scope(tenant_id, session_id)
        try:
            count = await self._long.consolidate(session_id=scoped)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_gateway.consolidate_failed: %s", exc)
            return 0
        return int(count or 0)


def _lang_to_fact(raw: Any) -> MemoryFact:
    """Преобразование LangMem-результата → :class:`MemoryFact`.

    Поддерживает 3 формата ввода:
        * dict с полями ``content``, ``confidence``, ``tags``, ``source_session_id``;
        * объект с этими же атрибутами (pydantic / dataclass);
        * строка — wrap в ``MemoryFact(content=raw, confidence=1.0)``.
    """
    if isinstance(raw, MemoryFact):
        return raw
    if isinstance(raw, str):
        return MemoryFact(content=raw, confidence=1.0)
    if isinstance(raw, dict):
        return MemoryFact(
            content=str(raw.get("content", "")),
            confidence=float(raw.get("confidence", 1.0) or 1.0),
            source_session_id=raw.get("source_session_id"),
            tags=tuple(raw.get("tags") or ()),
        )
    return MemoryFact(
        content=str(getattr(raw, "content", str(raw))),
        confidence=float(getattr(raw, "confidence", 1.0) or 1.0),
        source_session_id=getattr(raw, "source_session_id", None),
        tags=tuple(getattr(raw, "tags", ()) or ()),
    )


@app_state_singleton("memory_gateway")
def get_memory_gateway() -> UnifiedMemoryGateway:
    """Block 4.1: singleton :class:`UnifiedMemoryGateway` через app.state.

    Регистрация выполняется в ``infrastructure/application/service_setup.py``
    при старте приложения с composition:
        UnifiedMemoryGateway(short_term=agent_memory_svc, long_term=langmem_svc).

    Без app.state — поднимает RuntimeError (signal misconfiguration).
    """
    raise RuntimeError(
        "memory_gateway не зарегистрирован — убедитесь, что service_setup "
        "выполнил app.state.memory_gateway = UnifiedMemoryGateway(...)"
    )
