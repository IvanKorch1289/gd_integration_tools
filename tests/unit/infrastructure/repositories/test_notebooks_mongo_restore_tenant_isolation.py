"""v6 W3.2 contract test (4/6) — NotebooksMongoRepository.restore_version tenant isolation.

Per v6 §10 W3 spec: «Для каждого USER_DATA callsite — negative
cross-tenant test».

MongoNotebookRepository.restore_version() в src/backend/infrastructure/
repositories/notebooks_mongo.py:153 (restore_version → get) был
классифицирован как USER_DATA в W3.1 — нет tenant filter на MongoDB
lookup.

Этот тест ДОКУМЕНТИРУЕТ gap (debt) — не fix. Per v6 §3: «расхождение
runtime != architecture фиксируй как debt».

NB: separate file от test_notebooks_mongo_tenant_isolation.py — отдельный
callsite (restore_version vs append_version path). Uses same _FakeAsyncIOMotorClient.
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeAsyncIOMotorClient:
    """Minimal AsyncIOMotorClient stub with find_one/find/insert_one/update_one."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs

    def __call__(self) -> _FakeAsyncIOMotorClient:
        return self

    @property
    def collection(self):  # type: ignore[no-untyped-def]
        """Stub для client.collection() — принимает collection name (ignored)."""

        def _factory(_name: str) -> "_FakeAsyncIOMotorCollection":
            return _FakeAsyncIOMotorCollection(self._docs)

        return _factory

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


class _FakeAsyncIOMotorCollection:
    """Minimal collection stub supporting update_one / find_one."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> Any:
        doc_id = query.get("_id")
        if doc_id and doc_id in self._docs:
            return type("UpdateResult", (), {"modified_count": 1})()
        return type("UpdateResult", (), {"modified_count": 0})()

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        doc_id = query.get("_id")
        return self._docs.get(doc_id) if doc_id else None


@pytest.fixture()
def fake_mongo_with_tenant_a_data():
    """Fake mongo с notebook, принадлежащей tenant_A."""
    return {
        "nb-restore-1": {
            "_id": "nb-restore-1",
            "tenant_id": "tenant_A",
            "title": "Tenant A Restore Notebook",
            "created_by": "tenant_A_user",
            "versions": [
                {
                    "version": 1,
                    "content": "v1 content",
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
def repo(fake_mongo_with_tenant_a_data):
    """MongoNotebookRepository с fake mongo client."""
    from src.backend.infrastructure.repositories import notebooks_mongo as nm_mod

    fake_client = _FakeAsyncIOMotorClient(fake_mongo_with_tenant_a_data)
    yield nm_mod.MongoNotebookRepository(client_factory=lambda: fake_client)


@pytest.mark.asyncio
async def test_restore_version_does_not_filter_by_tenant(repo):
    """Per W3.1 classification: MongoNotebookRepository.restore_version НЕ фильтрует по tenant.

    Tenant A notebook → tenant B caller пытается restore version →
    должен fail per ADR-0345, но current code возвращает notebook без
    tenant check (BUG).

    Per v6 W3.2: SHOULD return None (tenant filter). Current behavior:
    proceed with restore (BUG). Negative test FAILS until tenant fix.
    """
    # Simulate tenant B caller attempting to restore version of tenant A's
    # notebook. Per v6 W3.2: SHOULD return None (no permission to access
    # other tenant's notebook). Current behavior (BUG): proceeds with restore.
    result = await repo.restore_version(
        notebook_id="nb-restore-1", version=1, changed_by="tenant_B_user"
    )

    # Current behavior (BUG): restore succeeds (returns new notebook).
    # After tenant-isolation fix: should return None (no cross-tenant access).
    assert result is None, (
        f"TENANT_ISOLATION_DEBT: MongoNotebookRepository.restore_version "
        f"allowed tenant_B to restore tenant_A's notebook without tenant "
        f"filter. result={result}. Per v6 §10 W3 + ADR-0345 Option A: "
        f"должен быть tenant predicate filter. See docs/roadmap/"
        f"W3_UNKNOWN_OWNERSHIP_CLASSIFICATION_2026-09-24.md раздел 2.1."
    )
