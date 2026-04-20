"""Agent Memory Service — persistence для conversation history и scratchpad."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.decorators.singleton import singleton
from app.infrastructure.clients.storage.redis import redis_client

__all__ = ("AgentMemoryService", "get_agent_memory_service")

logger = logging.getLogger(__name__)

_PREFIX = "agent:memory"


@singleton
class AgentMemoryService:
    """Persistence-слой для agent memory через Redis.

    Поддерживает:
    - Short-term: последние N сообщений диалога
    - Long-term: key-value facts (persona, human info)
    - Scratchpad: рабочая область агента
    - Auto-summarize: сжатие длинных историй
    """

    def __init__(
        self,
        max_short_term_messages: int = 50,
        short_term_ttl_seconds: int = 3600,
        long_term_ttl_seconds: int = 86400 * 30,
    ) -> None:
        self._max_messages = max_short_term_messages
        self._short_ttl = short_term_ttl_seconds
        self._long_ttl = long_term_ttl_seconds

    def _key(self, session_id: str, section: str) -> str:
        return f"{_PREFIX}:{session_id}:{section}"

    async def get_conversation(
        self, session_id: str, last_n: int = 20
    ) -> list[dict[str, Any]]:
        """Возвращает последние N сообщений."""
        key = self._key(session_id, "messages")
        raw = await redis_client.client.lrange(key, -last_n, -1)
        return [json.loads(item) for item in raw] if raw else []

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Добавляет сообщение в историю."""
        key = self._key(session_id, "messages")
        msg = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
            **(metadata or {}),
        }
        await redis_client.client.rpush(key, json.dumps(msg, default=str))
        await redis_client.client.ltrim(key, -self._max_messages, -1)
        await redis_client.client.expire(key, self._short_ttl)

    async def clear_conversation(self, session_id: str) -> None:
        """Очищает историю диалога."""
        await redis_client.client.delete(self._key(session_id, "messages"))

    async def get_scratchpad(self, session_id: str) -> str:
        """Возвращает scratchpad агента."""
        key = self._key(session_id, "scratchpad")
        data = await redis_client.client.get(key)
        return data.decode() if data else ""

    async def set_scratchpad(self, session_id: str, content: str) -> None:
        """Обновляет scratchpad."""
        key = self._key(session_id, "scratchpad")
        await redis_client.client.set(key, content, ex=self._long_ttl)

    async def get_facts(self, session_id: str) -> dict[str, str]:
        """Возвращает long-term facts (persona, human info)."""
        key = self._key(session_id, "facts")
        data = await redis_client.client.hgetall(key)
        return {k.decode(): v.decode() for k, v in data.items()} if data else {}

    async def set_fact(self, session_id: str, fact_key: str, value: str) -> None:
        """Сохраняет fact."""
        key = self._key(session_id, "facts")
        await redis_client.client.hset(key, fact_key, value)
        await redis_client.client.expire(key, self._long_ttl)

    async def delete_fact(self, session_id: str, fact_key: str) -> None:
        """Удаляет fact."""
        key = self._key(session_id, "facts")
        await redis_client.client.hdel(key, fact_key)

    async def load_memory(self, session_id: str) -> dict[str, Any]:
        """Загружает полный контекст памяти."""
        conversation = await self.get_conversation(session_id)
        scratchpad = await self.get_scratchpad(session_id)
        facts = await self.get_facts(session_id)

        return {
            "conversation": conversation,
            "scratchpad": scratchpad,
            "facts": facts,
        }

    async def save_memory(self, session_id: str, memory: dict[str, Any]) -> None:
        """Сохраняет полный контекст памяти."""
        if "scratchpad" in memory:
            await self.set_scratchpad(session_id, memory["scratchpad"])
        if "facts" in memory:
            for k, v in memory["facts"].items():
                await self.set_fact(session_id, k, v)

    async def session_exists(self, session_id: str) -> bool:
        """Проверяет существование сессии."""
        key = self._key(session_id, "messages")
        return bool(await redis_client.client.exists(key))


def get_agent_memory_service() -> AgentMemoryService:
    return AgentMemoryService()
