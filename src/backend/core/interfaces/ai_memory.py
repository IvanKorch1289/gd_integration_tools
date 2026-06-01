"""MemoryProtocol — контракт памяти для AI-агентов (ADR-NEW-18, S24 W3 + S27 W3).

Назначение
----------
Единый абстрактный контракт памяти для:

* LangGraph Checkpointer (state snapshots между нодами графа);
* Mem0 (semantic / long-term memory с PII-tokenization);
* AgentMemory Redis (legacy short-term conversation history).

Используется DSL-процессорами :class:`MemoryRecallProcessor` и
:class:`MemoryStoreProcessor` (S27 W3) для декларативного описания
RAG / agent-памяти в маршрутах.

Namespace
---------
Конвенция namespace: ``"<tenant_id>:<scope>"`` (см. capability
``ai.memory.read`` / ``ai.memory.write`` в ADR-NEW-18). Это позволяет
multi-tenant изоляцию и явное scoping (например, ``"acme:credit_chat"``,
``"acme:*"``).

Расширение
----------
Конкретные backends живут в ``services/ai/memory/`` (S24 W3 carryover):

* :class:`LangGraphMemoryAdapter` — wrap над AsyncPostgresSaver;
* :class:`Mem0MemoryAdapter` — wrap над mem0ai SDK;
* :class:`AgentMemoryAdapter` — Redis-backed legacy mapping.

См. также
---------
* :mod:`src.backend.core.security.capabilities.vocabulary` — capabilities
  ``ai.memory.{read,write,delete}``.
* docs/adr/0064-ai-memory-protocol.md.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

__all__ = ("MemoryProtocol", "MemoryRecord")


MemoryRecord = Mapping[str, Any]
"""Запись памяти — словарь с произвольными полями.

Минимально содержит ``key`` / ``value``; backend-специфичные адаптеры
могут включать ``score`` (для semantic search), ``metadata``,
``created_at`` и т.д.
"""


@runtime_checkable
class MemoryProtocol(Protocol):
    """Контракт памяти для AI-агентов.

    Backend-агностичный API: одинаково реализуется через
    LangGraph Checkpointer, Mem0, AgentMemory (Redis).

    Все методы — async. Сценарии recall/store/delete отображаются
    1:1 на capability ``ai.memory.{read,write,delete}``.

    Примечание:
        Protocol объявлен :func:`runtime_checkable` — что позволяет
        ``isinstance(backend, MemoryProtocol)`` в DI / тестах.
        Реализация может быть как обычный класс, так и dataclass.
    """

    async def recall(
        self, namespace: str, query: str, *, k: int = 5
    ) -> list[MemoryRecord]:
        """Поиск релевантных записей памяти (RAG-style retrieval).

        Args:
            namespace: ``"<tenant_id>:<scope>"`` — изоляция по tenant.
            query: Текстовый запрос (для semantic search) или ключ-подстрока
                (для key-based backends).
            k: Максимальное число возвращаемых записей.

        Returns:
            Список :class:`MemoryRecord` (мапка с произвольными полями),
            отсортированный backend'ом по релевантности. Пустой список
            при отсутствии совпадений или недоступности backend'а
            (не должен поднимать исключение).
        """
        ...

    async def store(
        self, namespace: str, key: str, value: Any, *, ttl_s: int | None = None
    ) -> None:
        """Сохранить запись в памяти.

        Args:
            namespace: ``"<tenant_id>:<scope>"`` — изоляция по tenant.
            key: Уникальный ключ записи (deterministic для idempotency).
            value: Произвольный сериализуемый объект; backend
                сам решает формат (JSON / pickle / embeddings).
            ttl_s: Опц. TTL в секундах; ``None`` — без expiration.
        """
        ...

    async def delete(self, namespace: str, key: str) -> None:
        """Удалить запись (idempotent).

        Args:
            namespace: ``"<tenant_id>:<scope>"`` — изоляция по tenant.
            key: Ключ записи. При отсутствии — silent no-op.

        Notes:
            Используется для GDPR / 152-ФЗ user-erasure
            (capability ``ai.memory.delete``).
        """
        ...
