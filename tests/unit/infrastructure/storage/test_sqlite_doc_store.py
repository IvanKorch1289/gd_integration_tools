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
async def test_ensure_namespace_trailing_newline_rejected(
    doc_store: SqliteDocStore,
) -> None:
    """Trailing newline запрещён: канон использует ``\\Z``, а не ``$``."""
    with pytest.raises(ValueError, match="Некорректный namespace"):
        await doc_store._ensure_namespace("ns1\n")


@pytest.mark.asyncio
async def test_ensure_namespace_known_cache(doc_store: SqliteDocStore) -> None:
    table1 = await doc_store._ensure_namespace("ns1")
    table2 = await doc_store._ensure_namespace("ns1")
    assert table1 == table2


# ─────────────────── S-30 (Wave 13, Q18): SQL-инъекция через ключ фильтра ───────────────────


@pytest.mark.asyncio
async def test_find_rejects_injected_filter_key(doc_store: SqliteDocStore) -> None:
    """Ключ фильтра с SQL-инъекцией → ValueError (SQL не исполняется)."""
    await doc_store.insert("ns1", {"t": "a"})
    with pytest.raises(ValueError, match="Недопустимый ключ фильтра"):
        await doc_store.find("ns1", filters={"t') OR 1=1 OR ('1'='1": "a"}, limit=10)


@pytest.mark.asyncio
async def test_find_injection_does_not_leak_rows(doc_store: SqliteDocStore) -> None:
    """Инъекция не возвращает «все строки» — запрос отклонён до выполнения."""
    await doc_store.insert("ns1", {"t": "a"})
    await doc_store.insert("ns1", {"t": "b"})
    with pytest.raises(ValueError):
        await doc_store.find("ns1", filters={"t') OR 1=1 --": "a"}, limit=10)
    # Данные не пострадали, обычный запрос возвращает ровно оба документа.
    docs = await doc_store.find("ns1", limit=10)
    assert len(docs) == 2


@pytest.mark.asyncio
async def test_find_rejects_non_identifier_filter_keys(
    doc_store: SqliteDocStore,
) -> None:
    """Пробелы, кавычки и спецсимволы в ключе фильтра запрещены."""
    for bad_key in ("t; DROP TABLE doc_ns1", "t name", "t'name", "1t", ""):
        with pytest.raises(ValueError, match="Недопустимый ключ фильтра"):
            await doc_store.find("ns1", filters={bad_key: "a"}, limit=10)


@pytest.mark.asyncio
async def test_find_allows_nested_json_path_filter(doc_store: SqliteDocStore) -> None:
    """Точка в ключе допустима — это вложенный JSON-путь (``$.meta.v``)."""
    await doc_store.insert("ns1", {"meta": {"v": 1}})
    await doc_store.insert("ns1", {"meta": {"v": 2}})
    docs = await doc_store.find("ns1", filters={"meta.v": 2}, limit=10)
    assert len(docs) == 1
    assert docs[0]["meta"] == {"v": 2}
