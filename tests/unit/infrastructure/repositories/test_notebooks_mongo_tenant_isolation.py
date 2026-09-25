"""v6 W3.2 contract test (3/6) — NotebooksMongoRepository tenant isolation.

Per v6 §10 W3 spec: «Для каждого USER_DATA callsite — negative
cross-tenant test».

После 25.09 audit fix NotebooksMongoRepository.get() ТРЕБУЕТ tenant_id
(keyword-only, no default) — fail-closed per ADR-0345. Empty/None tenant
→ None. Cross-tenant lookup → None. Own-tenant lookup → notebook.
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
            "title": "Tenant A Notebook",
            "created_by": "tenant_A_user",
            "metadata": {"tenant_id": "tenant_A"},
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
    yield nm_mod.MongoNotebookRepository(client_factory=lambda: fake_client)


@pytest.mark.asyncio
async def test_get_returns_none_for_unrelated_notebook(repo):
    """Sanity: get(unknown_id, tenant_id=...) returns None."""
    result = await repo.get("nonexistent", tenant_id="tenant_a")
    assert result is None


@pytest.mark.asyncio
async def test_get_cross_tenant_returns_none(repo):
    """Tenant B читает tenant A notebook → None (negative test)."""
    # Tenant B пытается прочитать tenant A's notebook.
    result = await repo.get("nb-123", tenant_id="tenant_B")
    assert result is None, (
        f"TENANT_ISOLATION_FAILED: cross-tenant get returned {result} "
        f"instead of None."
    )


@pytest.mark.asyncio
async def test_get_own_tenant_succeeds(repo):
    """Tenant A читает свой notebook → notebook (positive test)."""
    result = await repo.get("nb-123", tenant_id="tenant_A")
    assert result is not None
    assert result.metadata.get("tenant_id") == "tenant_A"


@pytest.mark.asyncio
async def test_get_empty_tenant_returns_none(repo):
    """Empty tenant_id → None (fail-closed per ADR-0345)."""
    result = await repo.get("nb-123", tenant_id="")
    assert result is None, (
        f"FAIL_CLOSED_VIOLATION: empty tenant_id returned {result} instead of None."
    )
