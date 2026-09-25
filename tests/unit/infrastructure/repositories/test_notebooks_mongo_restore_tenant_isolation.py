"""v6 W3.2 contract test (4/6) — NotebooksMongoRepository tenant isolation.

Per v6 §10 W3 spec: «Для каждого USER_DATA callsite — negative
cross-tenant test».

После 25.09 audit fix MongoNotebookRepository.restore_version() и
append_version() принимают ``tenant_id`` (keyword-only) и фильтруют
по ``notebook.metadata["tenant_id"]``. Cross-tenant restore/append
возвращает ``None`` без side-effects (ADR-0345 Option A).

NB: separate file от test_notebooks_mongo_tenant_isolation.py — отдельный
callsite (restore_version vs append_version path).
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
            "title": "Tenant A Restore Notebook",
            "created_by": "tenant_A_user",
            "metadata": {"tenant_id": "tenant_A"},
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
async def test_restore_version_cross_tenant_returns_none(repo):
    """Tenant B пытается restore tenant A's notebook → None (ADR-0345)."""
    # Tenant B caller attempting to restore version of tenant A's notebook.
    result = await repo.restore_version(
        notebook_id="nb-restore-1",
        version=1,
        changed_by="tenant_B_user",
        tenant_id="tenant_B",
    )
    assert result is None, (
        f"TENANT_ISOLATION_FAILED: restore_version cross-tenant returned "
        f"{result} instead of None. Tenant B restored tenant_A's notebook!"
    )


@pytest.mark.asyncio
async def test_restore_version_own_tenant_succeeds(repo):
    """Tenant A успешно restore свой notebook (positive test).

    fake mongo update_one не мутирует in-memory dict, поэтому проверяем
    только что: tenant-filtered get() возвращает notebook (без ошибки
    tenant mismatch). Версия инкремент — отдельный сценарий (требует
    реальной mongo с поддержкой $push в update_one).
    """
    result = await repo.restore_version(
        notebook_id="nb-restore-1",
        version=1,
        changed_by="tenant_A_user",
        tenant_id="tenant_A",
    )
    assert result is not None
    assert result.metadata.get("tenant_id") == "tenant_A"


@pytest.mark.asyncio
async def test_append_version_cross_tenant_returns_none(repo):
    """Tenant B пытается append version в tenant A's notebook → None."""
    result = await repo.append_version(
        notebook_id="nb-restore-1",
        content="hostile content",
        changed_by="tenant_B_user",
        tenant_id="tenant_B",
    )
    assert result is None, (
        f"TENANT_ISOLATION_FAILED: append_version cross-tenant returned "
        f"{result} instead of None."
    )


@pytest.mark.asyncio
async def test_append_version_own_tenant_succeeds(repo):
    """Tenant A успешно append новую версию в свой notebook (positive test)."""
    result = await repo.append_version(
        notebook_id="nb-restore-1",
        content="new content",
        changed_by="tenant_A_user",
        tenant_id="tenant_A",
    )
    assert result is not None
    assert result.metadata.get("tenant_id") == "tenant_A"
