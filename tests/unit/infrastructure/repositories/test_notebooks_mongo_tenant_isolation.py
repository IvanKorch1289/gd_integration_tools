"""v6 W3.2 contract test (3/6) — NotebooksMongoRepository tenant isolation.

Per v6 §10 W3 spec: «Для каждого USER_DATA callsite — negative
cross-tenant test».

NotebooksMongoRepository.get() в src/backend/infrastructure/repositories/
notebooks_mongo.py:147 (append_version → get) и :153 (restore_version
→ get) были классифицированы как USER_DATA в W3.1 — нет tenant filter
на MongoDB lookup. Per ADR-0345 Option A требуется tenant predicate.

Этот тест ДОКУМЕНТИРУЕТ gap (debt) — не fix.
Negative test FAILING = current code lacks tenant isolation (real P0).
Per v6 §3: «расхождение runtime != architecture фиксируй как debt,
а не «исправляй» молча».
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeAsyncIOMotorCollection:
    """Minimal AsyncIOMotorCollection stub с find_one."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs

    async def find_one(
        self, collection: str, query: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Find single doc by query match (simplified)."""
        doc_id = query.get("_id")
        if doc_id is None:
            return None
        return self._docs.get(doc_id)


class _FakeAsyncIOMotorClient:
    """Minimal AsyncIOMotorClient stub with find_one(collection, query)."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs
        self._collections = _FakeAsyncIOMotorCollection(docs)

    def __call__(self) -> _FakeAsyncIOMotorClient:
        return self

    async def find_one(
        self, collection: str, query: dict[str, Any]
    ) -> dict[str, Any] | None:
        doc_id = query.get("_id")
        if doc_id is None:
            return None
        return self._docs.get(doc_id)

    async def find(
        self, collection: str, query: dict[str, Any], limit: int | None = None
    ) -> list[dict[str, Any]]:
        return list(self._docs.values())[:limit]

    async def insert_one(self, collection: str, doc: dict[str, Any]) -> Any:
        self._docs[doc["_id"]] = doc
        return type("InsertedId", (), {"inserted_id": doc["_id"]})()

    async def update_one(
        self, collection: str, query: dict[str, Any], update: dict[str, Any]
    ) -> Any:
        doc_id = query.get("_id")
        if doc_id and doc_id in self._docs:
            return type("UpdateResult", (), {"modified_count": 1})()
        return type("UpdateResult", (), {"modified_count": 0})()


@pytest.fixture()
def fake_mongo_with_tenant_a_data():
    """Fake mongo с notebook, принадлежащей tenant_A."""
    return {
        "nb-123": {
            "_id": "nb-123",
            "tenant_id": "tenant_A",
            "title": "Tenant A Notebook",
            "created_by": "tenant_A_user",
            "versions": [
                {
                    "version": 1,
                    "content": "secret",
                    "changed_by": "tenant_A_user",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
            "latest_version": 1,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
    }


@pytest.fixture()
def repo(fake_mongo_with_tenant_a_data, monkeypatch):
    """NotebooksMongoRepository с fake mongo client."""
    from src.backend.infrastructure.repositories import notebooks_mongo as nm_mod

    fake_client = _FakeAsyncIOMotorClient(fake_mongo_with_tenant_a_data)

    # Repository uses ``client_factory`` или get_mongo_client.
    # Моно-патчим через __init__ client_factory parameter.
    yield nm_mod.MongoNotebookRepository(client_factory=lambda: fake_client)


@pytest.mark.asyncio
async def test_get_returns_none_for_unrelated_notebook(repo):
    """Sanity: get(unknown_id) returns None."""
    result = await repo.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_does_not_filter_by_tenant(repo):
    """Per W3.1 classification: NotebooksMongoRepository.get НЕ фильтрует по tenant.

    Tenant A создаёт notebook → tenant B читает → возвращается
    payload (НЕ tenant-scoped).

    Per v6 W3.2: SHOULD return None. Current behavior: returns. Negative
    test FAILS until tenant-isolation fix.
    """
    # Simulate tenant B caller attempting to read tenant A's notebook.
    # Per v6 W3.2: SHOULD return None (tenant filter).
    # Current behavior (BUG): returns tenant A's payload.
    result = await repo.get("nb-123")

    assert result is None, (
        f"TENANT_ISOLATION_DEBT: NotebooksMongoRepository.get(notebook_id) "
        f"returned notebook from tenant A without tenant filter. "
        f"notebook_id=nb-123, result.tenant_id={getattr(result, 'tenant_id', 'n/a')}. "
        f"Per v6 §10 W3 + ADR-0345 Option A: должен быть tenant predicate "
        f"filter. See docs/roadmap/W3_UNKNOWN_OWNERSHIP_CLASSIFICATION_2026-09-24.md "
        f"раздел 2.1."
    )
