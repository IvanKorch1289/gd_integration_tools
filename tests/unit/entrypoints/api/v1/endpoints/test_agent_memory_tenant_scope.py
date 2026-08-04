"""Регрессии tenant isolation для AgentMemory REST и service."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints import agent_memory as endpoint_module
from src.backend.entrypoints.middlewares.request_context import RequestContextMiddleware
from src.backend.services.ai.agent_memory import AgentMemoryService

pytestmark = pytest.mark.unit


class _FakeCollection:
    """Минимальная Mongo collection для удаления сообщений в тестах."""

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


@pytest.mark.asyncio
async def test_service_tenant_a_cannot_read_tenant_b_session() -> None:
    """Tenant A не читает сообщения tenant B при одинаковом session_id."""
    mongo = _FakeMongoClient()
    service = AgentMemoryService(client_factory=mongo.factory)

    await service.add_message(
        "shared",
        role="user",
        content="tenant-b-secret",
        metadata={"session_id": "tenant_a:shared"},
        tenant_id="tenant_b",
    )

    assert await service.get_conversation("shared", tenant_id="tenant_a") == []
    tenant_b_messages = await service.get_conversation("shared", tenant_id="tenant_b")
    assert [message["content"] for message in tenant_b_messages] == ["tenant-b-secret"]


def test_rest_tenant_a_cannot_read_tenant_b_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST извлекает tenant из RequestContext и изолирует одинаковый session_id."""
    mongo = _FakeMongoClient()
    service = AgentMemoryService(client_factory=mongo.factory)
    monkeypatch.setattr(endpoint_module, "get_agent_memory_service", lambda: service)
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(endpoint_module.router, prefix="/agent_memory")

    with TestClient(app) as client:
        created = client.post(
            "/agent_memory/sessions/shared/messages",
            headers={"X-Tenant-ID": "tenant_b"},
            json={"role": "user", "content": "tenant-b-secret"},
        )
        tenant_a = client.get(
            "/agent_memory/sessions/shared/messages",
            headers={"X-Tenant-ID": "tenant_a"},
        )
        tenant_b = client.get(
            "/agent_memory/sessions/shared/messages",
            headers={"X-Tenant-ID": "tenant_b"},
        )

    assert created.status_code == 200
    assert tenant_a.status_code == 200
    assert tenant_a.json() == {"items": []}
    assert tenant_b.status_code == 200
    assert [item["content"] for item in tenant_b.json()["items"]] == ["tenant-b-secret"]
