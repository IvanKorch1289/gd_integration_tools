"""Тесты ``SqliteDocStore`` (Wave 21.3c)."""

from __future__ import annotations

import pytest

from src.infrastructure.storage.sqlite_doc_store import SqliteDocStore


@pytest.mark.asyncio
async def test_insert_and_get_round_trip(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    doc_id = await store.insert("notes", {"title": "T1", "body": "hello"})
    assert isinstance(doc_id, str) and doc_id
    got = await store.get("notes", doc_id)
    assert got == {"title": "T1", "body": "hello"}


@pytest.mark.asyncio
async def test_insert_with_explicit_id(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    doc_id = await store.insert("notes", {"k": "v"}, doc_id="custom-id")
    assert doc_id == "custom-id"
    assert await store.get("notes", "custom-id") == {"k": "v"}


@pytest.mark.asyncio
async def test_update_merges(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    doc_id = await store.insert("notes", {"a": 1, "b": 2})
    assert await store.update("notes", doc_id, {"b": 3, "c": 4}) is True
    assert await store.get("notes", doc_id) == {"a": 1, "b": 3, "c": 4}


@pytest.mark.asyncio
async def test_update_returns_false_when_missing(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    assert await store.update("notes", "missing", {"x": 1}) is False


@pytest.mark.asyncio
async def test_delete(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    doc_id = await store.insert("notes", {"x": 1})
    assert await store.delete("notes", doc_id) is True
    assert await store.delete("notes", doc_id) is False
    assert await store.get("notes", doc_id) is None


@pytest.mark.asyncio
async def test_find_with_filter(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    for status in ("active", "active", "archived"):
        await store.insert("orders", {"status": status})
    active = await store.find("orders", filters={"status": "active"})
    assert len(active) == 2
    assert all(d["status"] == "active" for d in active)


@pytest.mark.asyncio
async def test_count_with_and_without_filter(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    for i in range(5):
        await store.insert("orders", {"i": i, "even": i % 2 == 0})
    assert await store.count("orders") == 5
    assert await store.count("orders", filters={"even": True}) == 3


@pytest.mark.asyncio
async def test_invalid_namespace_rejected(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    with pytest.raises(ValueError, match="Некорректный namespace"):
        await store.insert("bad-namespace", {"a": 1})
    with pytest.raises(ValueError):
        await store.insert("docs; DROP TABLE", {"a": 1})


@pytest.mark.asyncio
async def test_find_pagination(tmp_path):
    store = SqliteDocStore(tmp_path / "docs.sqlite3")
    for i in range(10):
        await store.insert("items", {"i": i}, doc_id=f"id{i:02d}")
    page1 = await store.find("items", limit=3, offset=0)
    page2 = await store.find("items", limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 3
    assert {d["i"] for d in page1} & {d["i"] for d in page2} == set()
