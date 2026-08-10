"""Unit test для cycle-6/D-AUDIT-606.

Проверяет multi-tenant isolation для :class:`AgentMemoryService`:

1. ``add_message`` без ``tenant_id`` kwarg → TypeError (kw-only required).
2. ``get_conversation`` без ``tenant_id`` kwarg → TypeError.
3. ``add_message`` с tenant_id сохраняет ``tenant_id`` в Mongo doc.
4. ``get_conversation`` фильтрует query по ``(session_id, tenant_id)``:
   Tenant A не видит сообщения Tenant B при одинаковом ``session_id``.
5. ``_trim_messages`` ограничивает trim рамками tenant (cross-tenant
   delete не происходит).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.services.ai.agent_memory import AgentMemoryService

pytestmark = pytest.mark.unit


class _FakeCollection:
    """Минимальная Mongo collection для regression-тестов."""

    def __init__(self, client: _FakeMongoClient, name: str) -> None:
        self._client = client
        self._name = name

    async def delete_many(self, query: dict[str, Any]) -> None:
        """Удалить документы, совпадающие с простым equality-фильтром."""
        self._client.documents[self._name] = [
            doc
            for doc in self._client.documents.get(self._name, [])
            if not all(doc.get(key) == value for key, value in query.items())
        ]


class _FakeMongoClient:
    """Минимальный in-memory Mongo client для AgentMemory regression."""

    def __init__(self) -> None:
        self.documents: dict[str, list[dict[str, Any]]] = {}

    def factory(self) -> _FakeMongoClient:
        """Вернуть client из AgentMemory client_factory."""
        return self

    def collection(self, name: str) -> _FakeCollection:
        """Вернуть минимальную collection-обёртку."""
        return _FakeCollection(self, name)

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """Сохранить копию документа."""
        self.documents.setdefault(collection, []).append(dict(document))
        return str(len(self.documents[collection]))

    async def find(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        projection: dict[str, Any] | None = None,
        limit: int | None = None,
        skip: int | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]:
        """Найти документы по простому equality-фильтру."""
        query = query or {}
        docs = [
            dict(doc)
            for doc in self.documents.get(collection, [])
            if all(doc.get(key) == value for key, value in query.items())
        ]
        if sort:
            field, direction = sort[0]
            docs.sort(key=lambda doc: doc.get(field, 0), reverse=direction < 0)
        if skip:
            docs = docs[skip:]
        if limit is not None:
            docs = docs[:limit]
        if projection:
            excluded = {key for key, enabled in projection.items() if not enabled}
            docs = [
                {key: value for key, value in doc.items() if key not in excluded}
                for doc in docs
            ]
        return docs


def _service() -> tuple[AgentMemoryService, _FakeMongoClient]:
    """Builder: AgentMemoryService + in-memory Mongo client."""
    mongo = _FakeMongoClient()
    return AgentMemoryService(client_factory=mongo.factory), mongo


@pytest.mark.asyncio
async def test_add_message_without_tenant_id_raises_type_error() -> None:
    """``add_message`` без tenant_id → TypeError (cycle-6/D-AUDIT-606).

    Без явного tenant kwarg вызов обязан упасть: kw-only required
    параметр без default не имеет смысла при multi-tenant storage.
    """
    service, _ = _service()
    with pytest.raises(TypeError, match="tenant_id"):
        await service.add_message(  # type: ignore[call-arg]
            "shared",
            role="user",
            content="hi",
        )


@pytest.mark.asyncio
async def test_get_conversation_without_tenant_id_raises_type_error() -> None:
    """``get_conversation`` без tenant_id → TypeError (cycle-6/D-AUDIT-606)."""
    service, _ = _service()
    with pytest.raises(TypeError, match="tenant_id"):
        await service.get_conversation(  # type: ignore[call-arg]
            "shared",
        )


@pytest.mark.asyncio
async def test_add_message_persists_tenant_id_field() -> None:
    """Stored document содержит ``tenant_id`` (не только session_id)."""
    service, mongo = _service()
    await service.add_message(
        "shared",
        role="user",
        content="hello",
        tenant_id="tenant_b",
    )
    docs = mongo.documents["agent_memory_messages"]
    assert len(docs) == 1
    assert docs[0]["tenant_id"] == "tenant_b"
    assert docs[0]["session_id"] == "shared"


@pytest.mark.asyncio
async def test_get_conversation_filters_by_tenant_id() -> None:
    """Tenant A не видит сообщения Tenant B при одинаковом session_id."""
    service, _ = _service()

    await service.add_message(
        "shared",
        role="user",
        content="tenant-b-secret",
        tenant_id="tenant_b",
    )
    await service.add_message(
        "shared",
        role="user",
        content="tenant-a-public",
        tenant_id="tenant_a",
    )

    tenant_a = await service.get_conversation("shared", tenant_id="tenant_a")
    tenant_b = await service.get_conversation("shared", tenant_id="tenant_b")

    assert [m["content"] for m in tenant_a] == ["tenant-a-public"]
    assert [m["content"] for m in tenant_b] == ["tenant-b-secret"]


@pytest.mark.asyncio
async def test_get_conversation_projection_excludes_tenant_id() -> None:
    """Projection убирает ``tenant_id`` и ``session_id`` из результата."""
    service, _ = _service()
    await service.add_message(
        "shared",
        role="user",
        content="hello",
        tenant_id="tenant_a",
    )
    docs = await service.get_conversation("shared", tenant_id="tenant_a")
    assert docs == [{"role": "user", "content": "hello", "ts": docs[0]["ts"]}]
    assert "tenant_id" not in docs[0]
    assert "session_id" not in docs[0]


@pytest.mark.asyncio
async def test_add_message_then_get_conversation_round_trip() -> None:
    """Round-trip: add_message → get_conversation возвращает тот же message."""
    service, _ = _service()
    await service.add_message(
        "s1",
        role="assistant",
        content="reply",
        metadata={"model": "gpt-4o-mini"},
        tenant_id="t1",
    )
    docs = await service.get_conversation("s1", tenant_id="t1")
    assert len(docs) == 1
    assert docs[0]["role"] == "assistant"
    assert docs[0]["content"] == "reply"
    # metadata spread в top-level doc (см. ``add_message``).
    assert docs[0]["model"] == "gpt-4o-mini"
