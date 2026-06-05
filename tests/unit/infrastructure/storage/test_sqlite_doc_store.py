"""Unit-tests for SqliteDocStore backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.infrastructure.storage.sqlite_doc_store import SqliteDocStore


@pytest.fixture
def doc_store(tmp_path: Path) -> SqliteDocStore:
    return SqliteDocStore(path=tmp_path / "docs.db")


@pytest.mark.asyncio
async def test_insert_and_get(doc_store: SqliteDocStore) -> None:
    store = doc_store
    doc_id = await store.insert("ns1", {"name": "alice"})
    assert doc_id
    doc = await store.get("ns1", doc_id)
    assert doc == {"name": "alice"}


@pytest.mark.asyncio
async def test_get_missing(doc_store: SqliteDocStore) -> None:
    assert await doc_store.get("ns1", "missing") is None


@pytest.mark.asyncio
async def test_insert_with_custom_id(doc_store: SqliteDocStore) -> None:
    doc_id = await doc_store.insert("ns1", {"k": "v"}, doc_id="custom-1")
    assert doc_id == "custom-1"
    assert await doc_store.get("ns1", "custom-1") == {"k": "v"}


@pytest.mark.asyncio
async def test_update_existing(doc_store: SqliteDocStore) -> None:
    doc_id = await doc_store.insert("ns1", {"a": 1})
    ok = await doc_store.update("ns1", doc_id, {"b": 2})
    assert ok is True
    doc = await doc_store.get("ns1", doc_id)
    assert doc == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_update_missing(doc_store: SqliteDocStore) -> None:
    ok = await doc_store.update("ns1", "missing", {"b": 2})
    assert ok is False


@pytest.mark.asyncio
async def test_delete_existing(doc_store: SqliteDocStore) -> None:
    doc_id = await doc_store.insert("ns1", {"x": 1})
    ok = await doc_store.delete("ns1", doc_id)
    assert ok is True
    assert await doc_store.get("ns1", doc_id) is None


@pytest.mark.asyncio
async def test_delete_missing(doc_store: SqliteDocStore) -> None:
    ok = await doc_store.delete("ns1", "missing")
    assert ok is False


@pytest.mark.asyncio
async def test_find_without_filters(doc_store: SqliteDocStore) -> None:
    await doc_store.insert("ns1", {"i": 1})
    await doc_store.insert("ns1", {"i": 2})
    docs = await doc_store.find("ns1", limit=10)
    assert len(docs) == 2


@pytest.mark.asyncio
async def test_find_with_filters(doc_store: SqliteDocStore) -> None:
    await doc_store.insert("ns1", {"t": "a"})
    await doc_store.insert("ns1", {"t": "b"})
    docs = await doc_store.find("ns1", filters={"t": "a"}, limit=10)
    assert len(docs) == 1
    assert docs[0]["t"] == "a"


@pytest.mark.asyncio
async def test_find_limit_and_offset(doc_store: SqliteDocStore) -> None:
    for i in range(5):
        await doc_store.insert("ns1", {"i": i})
    docs = await doc_store.find("ns1", limit=2, offset=1)
    assert len(docs) == 2


@pytest.mark.asyncio
async def test_count_without_filters(doc_store: SqliteDocStore) -> None:
    await doc_store.insert("ns1", {"x": 1})
    await doc_store.insert("ns1", {"x": 2})
    assert await doc_store.count("ns1") == 2


@pytest.mark.asyncio
async def test_count_with_filters(doc_store: SqliteDocStore) -> None:
    await doc_store.insert("ns1", {"t": "a"})
    await doc_store.insert("ns1", {"t": "b"})
    assert await doc_store.count("ns1", filters={"t": "a"}) == 1


@pytest.mark.asyncio
async def test_ensure_namespace_invalid_name(doc_store: SqliteDocStore) -> None:
    with pytest.raises(ValueError, match="Некорректный namespace"):
        await doc_store._ensure_namespace("bad-namespace")


@pytest.mark.asyncio
async def test_ensure_namespace_known_cache(doc_store: SqliteDocStore) -> None:
    table1 = await doc_store._ensure_namespace("ns1")
    table2 = await doc_store._ensure_namespace("ns1")
    assert table1 == table2
