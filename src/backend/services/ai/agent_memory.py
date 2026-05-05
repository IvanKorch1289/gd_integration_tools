"""Долгосрочная память агентов (conversation/scratchpad/facts) на MongoDB.

Wave 0.10: бэкенд переехал из Redis в MongoDB — Redis не подходит для
постоянной памяти агентов (теряется при flush, нет аудита истории).
Публичный API ``AgentMemoryService`` сохранён для совместимости с
DSL-actions (``src/dsl/commands/setup.py``).

Хранилище:
* ``agent_memory_messages`` — по документу на сообщение,
  TTL-индекс по ``ts`` (по умолчанию 1 час, см. ``short_term_ttl_seconds``).
* ``agent_memory_scratchpad`` — singleton-документ на сессию,
  TTL-индекс по ``updated_at`` (30 дней).
* ``agent_memory_facts`` — по документу на (session_id, fact_key),
  TTL-индекс по ``updated_at`` (30 дней).

Создание TTL-индексов выполняется через ``ensure_indexes()`` — вызывается
из ``lifecycle.startup`` после старта MongoDB-клиента.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.di.providers import get_mongo_client_provider
from src.backend.core.interfaces.ai_clients import MongoClientProtocol

__all__ = ("AgentMemoryService", "get_agent_memory_service")

logger = logging.getLogger(__name__)

_MESSAGES = "agent_memory_messages"
_SCRATCHPAD = "agent_memory_scratchpad"
_FACTS = "agent_memory_facts"


class AgentMemoryService:
    """Persistence-слой для agent memory через MongoDB.

    Поддерживает:
    * **Short-term**: последние N сообщений диалога (TTL).
    * **Long-term**: key-value facts (persona, human info) с TTL.
    * **Scratchpad**: рабочая область агента (TTL).
    """

    def __init__(
        self,
        max_short_term_messages: int = 50,
        short_term_ttl_seconds: int = 3600,
        long_term_ttl_seconds: int = 86400 * 30,
        client_factory: Any | None = None,
    ) -> None:
        self._max_messages = max_short_term_messages
        self._short_ttl = short_term_ttl_seconds
        self._long_ttl = long_term_ttl_seconds
        # Wave 6.3: lazy-провайдер вместо direct infrastructure import.
        # Реальная фабрика резолвится в момент первого вызова `_client()`.
        self._client_factory = client_factory

    def _client(self) -> MongoClientProtocol:
        factory = self._client_factory or get_mongo_client_provider()
        return factory()

    async def ensure_indexes(self) -> None:
        """Создаёт TTL-индексы (idempotent). Вызывать после старта Mongo."""
        try:
            client = self._client()
            await client.collection(_MESSAGES).create_index(
                "ts", expireAfterSeconds=self._short_ttl, name="ttl_ts"
            )
            await client.collection(_MESSAGES).create_index(
                [("session_id", 1), ("ts", 1)], name="session_ts"
            )
            await client.collection(_SCRATCHPAD).create_index(
                "updated_at", expireAfterSeconds=self._long_ttl, name="ttl_updated_at"
            )
            await client.collection(_SCRATCHPAD).create_index(
                "session_id", unique=True, name="session_id_unique"
            )
            await client.collection(_FACTS).create_index(
                "updated_at", expireAfterSeconds=self._long_ttl, name="ttl_updated_at"
            )
            await client.collection(_FACTS).create_index(
                [("session_id", 1), ("fact_key", 1)],
                unique=True,
                name="session_fact_unique",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AgentMemory: ensure_indexes failed: %s", exc)

    async def get_conversation(
        self, session_id: str, last_n: int = 20
    ) -> list[dict[str, Any]]:
        client = self._client()
        docs = await client.find(
            _MESSAGES,
            query={"session_id": session_id},
            projection={"_id": 0, "session_id": 0},
            limit=last_n,
            sort=[("ts", -1)],
        )
        return list(reversed(docs))

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        client = self._client()
        doc = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "ts": time.time(),
            **(metadata or {}),
        }
        await client.insert_one(_MESSAGES, doc)
        # Trim до max_messages — оставляем только N последних.
        cnt = await client.count(_MESSAGES, {"session_id": session_id})
        if cnt > self._max_messages:
            keep_ts_doc = await client.find(
                _MESSAGES,
                query={"session_id": session_id},
                projection={"ts": 1, "_id": 0},
                limit=1,
                skip=cnt - self._max_messages,
                sort=[("ts", 1)],
            )
            if keep_ts_doc:
                cutoff = keep_ts_doc[0]["ts"]
                await client.collection(_MESSAGES).delete_many(
                    {"session_id": session_id, "ts": {"$lt": cutoff}}
                )

    async def clear_conversation(self, session_id: str) -> None:
        client = self._client()
        await client.collection(_MESSAGES).delete_many({"session_id": session_id})

    async def get_scratchpad(self, session_id: str) -> str:
        client = self._client()
        doc = await client.find_one(_SCRATCHPAD, {"session_id": session_id})
        return doc.get("content", "") if doc else ""

    async def set_scratchpad(self, session_id: str, content: str) -> None:
        client = self._client()
        await client.update_one(
            _SCRATCHPAD,
            query={"session_id": session_id},
            update={
                "session_id": session_id,
                "content": content,
                "updated_at": time.time(),
            },
            upsert=True,
        )

    async def get_facts(self, session_id: str) -> dict[str, str]:
        client = self._client()
        docs = await client.find(
            _FACTS,
            query={"session_id": session_id},
            projection={"_id": 0, "fact_key": 1, "value": 1},
            limit=1000,
        )
        return {d["fact_key"]: d["value"] for d in docs}

    async def set_fact(self, session_id: str, fact_key: str, value: str) -> None:
        client = self._client()
        await client.update_one(
            _FACTS,
            query={"session_id": session_id, "fact_key": fact_key},
            update={
                "session_id": session_id,
                "fact_key": fact_key,
                "value": value,
                "updated_at": time.time(),
            },
            upsert=True,
        )

    async def delete_fact(self, session_id: str, fact_key: str) -> None:
        client = self._client()
        await client.delete_one(
            _FACTS, {"session_id": session_id, "fact_key": fact_key}
        )

    async def load_memory(self, session_id: str) -> dict[str, Any]:
        return {
            "conversation": await self.get_conversation(session_id),
            "scratchpad": await self.get_scratchpad(session_id),
            "facts": await self.get_facts(session_id),
        }

    async def save_memory(self, session_id: str, memory: dict[str, Any]) -> None:
        if "scratchpad" in memory:
            await self.set_scratchpad(session_id, memory["scratchpad"])
        if "facts" in memory:
            for k, v in memory["facts"].items():
                await self.set_fact(session_id, k, v)

    async def session_exists(self, session_id: str) -> bool:
        client = self._client()
        return bool(await client.count(_MESSAGES, {"session_id": session_id}))


@app_state_singleton("agent_memory_service", factory=AgentMemoryService)
def get_agent_memory_service() -> AgentMemoryService:
    raise NotImplementedError  # заменяется декоратором
