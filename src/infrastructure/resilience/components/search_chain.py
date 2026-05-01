"""Wiring W26.4: Elasticsearch → SQLite FTS5.

Контракт callable: ``async def search(index: str, query: str, *, limit: int = 20) -> list[dict]``.

SQLite-FTS5 fallback ведёт минимальный snapshot-индекс. Schema
автогенерируется при первом обращении (CREATE VIRTUAL TABLE ... USING
fts5). Стриминг-индексирование документов — отдельный background-job
(вне scope W26).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

__all__ = ("SearchCallable", "build_search_fallbacks", "build_search_primary")

logger = logging.getLogger(__name__)

SearchCallable = Callable[..., Awaitable[list[dict[str, Any]]]]


async def _es_search(
    index: str, query: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    from src.infrastructure.clients.storage.elasticsearch import (
        get_elasticsearch_client,
    )

    client = get_elasticsearch_client()
    response = await client.search(
        index=index, query={"match": {"_all": query}}, size=limit
    )
    return [hit["_source"] for hit in response["hits"]["hits"]]


async def _sqlite_fts5_search(
    index: str, query: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """SQLite FTS5 fallback. Использует один файл per-index."""
    db_path = Path("var/db/search") / f"{index}.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def _do_search() -> list[dict[str, Any]]:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {index}_fts "
                "USING fts5(doc_id, content)"
            )
            cursor = conn.execute(
                f"SELECT doc_id, content, rank FROM {index}_fts "  # noqa: S608
                f"WHERE {index}_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    return await asyncio.to_thread(_do_search)


def build_search_primary() -> SearchCallable:
    return _es_search


def build_search_fallbacks() -> dict[str, SearchCallable]:
    return {"sqlite_fts5": _sqlite_fts5_search}
