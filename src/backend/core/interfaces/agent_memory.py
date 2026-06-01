"""Block 4.1 (gap-ai-4.1, ADR-0075): :class:`AgentMemoryGateway` Protocol.

Единая абстракция памяти AI-агентов поверх двух существующих сервисов:

* :class:`AgentMemoryService` (MongoDB) — short-term: conversation messages,
  scratchpad, key-value facts с TTL.
* :class:`LangMemService` (PG + Qdrant) — long-term: semantic facts через
  embeddings, ConsolidationEngine для batch-сжатия short-term → semantic.

Цель — устранить direct callsites ``AgentMemoryService.*`` и ``LangMemService.*``
в DSL processors / multi_agent supervisor / agents_pydantic / RAG ingest.
После Block 4.1 closure:

* ``grep -rn 'AgentMemoryService\\b' src/backend/{dsl,services/ai/agents_pydantic,
  services/ai/multi_agent}`` = 0 direct calls (только через gateway).
* Все методы принимают ``tenant_id: str`` обязательно (kw-only).

Архитектурная роль:
    Gateway инкапсулирует решение "куда писать/откуда читать" — short-term
    в Mongo (TTL-окно) или long-term в PG/Qdrant (semantic). Callers
    декларируют намерение через метод (get_messages vs recall_semantic) —
    реализация скрыта.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ("AgentMemoryGateway", "MemoryFact", "MemoryMessage")


@dataclass(frozen=True, slots=True)
class MemoryMessage:
    """Сообщение в conversation memory (short-term, TTL).

    Attributes:
        role: ``user`` / ``assistant`` / ``system`` / ``tool``.
        content: Текст сообщения.
        ts: Unix timestamp seconds (UTC).
        metadata: Произвольные поля (model, provider, cost_usd, …).
    """

    role: str
    content: str
    ts: float
    metadata: Mapping[str, object] = ()  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """Факт в semantic memory (long-term, persisted).

    Attributes:
        content: Текст факта (e.g. "User prefers Russian language").
        confidence: Уверенность в факте [0..1].
        source_session_id: Источник (session, в которой факт извлечён).
        tags: Категории факта (e.g. ``("preference", "language")``).
    """

    content: str
    confidence: float
    source_session_id: str | None = None
    tags: tuple[str, ...] = ()


@runtime_checkable
class AgentMemoryGateway(Protocol):
    """Block 4.1: единый Protocol для AI memory с tenant isolation."""

    async def get_messages(
        self, *, tenant_id: str, session_id: str, limit: int = 50
    ) -> list[MemoryMessage]:
        """Возвращает последние ``limit`` сообщений conversation (short-term).

        Args:
            tenant_id: Tenant обязателен (multi-tenant isolation).
            session_id: Идентификатор сессии диалога.
            limit: Максимум сообщений (по убыванию ts).

        Returns:
            Список ``MemoryMessage`` от старых к новым.
        """

    async def save_message(
        self,
        *,
        tenant_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: Mapping[str, object] | None = None,
    ) -> str:
        """Сохраняет одно сообщение в conversation memory.

        Returns:
            ``message_id`` (UUID или backend-specific id).
        """

    async def get_facts(
        self, *, tenant_id: str, session_id: str | None = None, limit: int = 50
    ) -> list[MemoryFact]:
        """Возвращает known facts (long-term).

        При ``session_id`` указан — только facts источника этой сессии,
        иначе global для tenant.
        """

    async def save_fact(
        self,
        *,
        tenant_id: str,
        content: str,
        confidence: float = 1.0,
        source_session_id: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> str:
        """Сохраняет факт в long-term memory (semantic store).

        Returns:
            ``fact_id``.
        """

    async def recall_semantic(
        self, *, tenant_id: str, query: str, top_k: int = 5
    ) -> list[MemoryFact]:
        """Semantic search facts по embedding(query)."""

    async def get_scratchpad(self, *, tenant_id: str, session_id: str) -> str | None:
        """Возвращает scratchpad сессии или None если пуст/отсутствует."""

    async def save_scratchpad(
        self, *, tenant_id: str, session_id: str, content: str
    ) -> None:
        """Записывает scratchpad (один документ на session)."""

    async def consolidate(self, *, tenant_id: str, session_id: str) -> int:
        """Block 4.2 entrypoint: short-term → semantic consolidation.

        Triggers ConsolidationEngine.run(session_id) либо аналог в backend.

        Returns:
            Количество новых facts, добавленных в semantic store.
        """
