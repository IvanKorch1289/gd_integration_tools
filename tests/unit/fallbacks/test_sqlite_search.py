"""Тесты ``SqliteFTS5Search`` (Wave 21.3c)."""

from __future__ import annotations

import pytest

from src.infrastructure.clients.storage.sqlite_search import SqliteFTS5Search


@pytest.mark.asyncio
async def test_index_and_search_string_query(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    await search.index_document("docs", {"title": "Hello world"}, doc_id="1")
    await search.index_document("docs", {"title": "Goodbye world"}, doc_id="2")
    results = await search.search("docs", "Hello")
    assert len(results) == 1
    assert results[0]["title"] == "Hello world"


@pytest.mark.asyncio
async def test_index_idempotent_replaces_existing(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    await search.index_document("docs", {"title": "v1"}, doc_id="x")
    await search.index_document("docs", {"title": "v2"}, doc_id="x")
    agg = await search.aggregate("docs", {"total": {}})
    assert agg["aggregations"]["total"]["value"] == 1


@pytest.mark.asyncio
async def test_bulk_index_count(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    docs = [{"id": str(i), "title": f"doc {i}"} for i in range(5)]
    result = await search.bulk_index("docs", docs, id_field="id")
    assert result == {"indexed": 5}
    agg = await search.aggregate("docs", {"total": {}})
    assert agg["aggregations"]["total"]["value"] == 5


@pytest.mark.asyncio
async def test_search_with_match_dict(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    await search.index_document("docs", {"title": "kotleta"}, doc_id="a")
    await search.index_document("docs", {"title": "borshch"}, doc_id="b")
    results = await search.search("docs", {"match": {"title": "kotleta"}})
    assert len(results) == 1
    assert results[0]["title"] == "kotleta"


@pytest.mark.asyncio
async def test_delete_document(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    await search.index_document("docs", {"title": "x"}, doc_id="1")
    assert await search.delete_document("docs", "1") is True
    assert await search.delete_document("docs", "1") is False


@pytest.mark.asyncio
async def test_ping_returns_true(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    assert await search.ping() is True


@pytest.mark.asyncio
async def test_invalid_index_name_rejected(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    with pytest.raises(ValueError, match="Некорректное имя индекса"):
        await search.index_document("bad-name", {"x": 1})


@pytest.mark.asyncio
async def test_create_index_creates_empty_table(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    await search.create_index("empty")
    agg = await search.aggregate("empty", {"total": {}})
    assert agg["aggregations"]["total"]["value"] == 0


@pytest.mark.asyncio
async def test_sort_top_level_key(tmp_path):
    search = SqliteFTS5Search(tmp_path / "fts.sqlite3")
    await search.index_document("scores", {"name": "a", "score": 5}, doc_id="1")
    await search.index_document("scores", {"name": "b", "score": 9}, doc_id="2")
    await search.index_document("scores", {"name": "c", "score": 2}, doc_id="3")
    results = await search.search(
        "scores", "", size=10, sort=[{"score": "desc"}]
    )
    # FTS5 без MATCH-фильтра возвращает все документы.
    assert [d["score"] for d in results] == [9, 5, 2]
