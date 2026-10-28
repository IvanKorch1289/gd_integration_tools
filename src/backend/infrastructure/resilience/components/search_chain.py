"""Wiring W26.4: Elasticsearch → SQLite FTS5.

Контракт callable: ``async def search(index: str, query: str, *, limit: int = 20) -> list[dict]``.

SQLite-FTS5 fallback ведёт минимальный snapshot-индекс. Schema
автогенерируется при первом обращении (CREATE VIRTUAL TABLE ... USING
fts5). Стриминг-индексирование документов — отдельный background-job
(вне scope W26).

S-30 (Wave 13, Q18): ``index`` подставляется и в имя файла БД, и в имя
виртуальной таблицы FTS5 — bind-параметры к идентификаторам неприменимы,
поэтому имя валидируется allowlist-регексом ``validate_identifier``
ДО создания файла/таблицы.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from src.backend.core.utils.sql_identifiers import validate_identifier

__all__ = ("SearchCallable", "build_search_fallbacks", "build_search_primary")


SearchCallable = Callable[..., Awaitable[list[dict[str, Any]]]]


async def _es_search(
    index: str, query: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    from src.backend.infrastructure.clients.storage.elasticsearch import (
        get_elasticsearch_client,
    )

    client = get_elasticsearch_client()
    response = await client.search(
        index=index, query={"match": {"_all": query}}, size=limit
    )
    return [hit["_source"] for hit in response["hits"]["hits"]]  # type: ignore[call-overload]


async def _sqlite_fts5_search(
    index: str, query: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """SQLite FTS5 fallback. Использует один файл per-index.

    Args:
        index: Имя индекса (allowlist-идентификатор).
        query: FTS5 MATCH-запрос (bind-параметр).
        limit: Максимум результатов.

    Returns:
        Список найденных документов.

    Raises:
        ValueError: Если ``index`` не является валидным SQL-идентификатором.

    """
    # S-30 (Wave 13, Q18): валидация ДО создания файла/таблицы.
    validate_identifier(index, context="search_chain.sqlite_fts5.index")
    db_path = Path("var/db/search") / f"{index}.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def _do_search() -> list[dict[str, Any]]:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {index}_fts "  # noqa: S608  # nosec B608 — index: allowlist (validate_identifier)
                "USING fts5(doc_id, content)"
            )
            cursor = conn.execute(
                f"SELECT doc_id, content, rank FROM {index}_fts "  # noqa: S608  # nosec B608 — index: allowlist (validate_identifier), значения: bind-параметры
                f"WHERE {index}_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    return await asyncio.to_thread(_do_search)


def build_search_primary() -> SearchCallable:
    """Возвращает primary поиск (Elasticsearch)."""
    return _es_search


def build_search_fallbacks() -> dict[str, SearchCallable]:
    """Возвращает словарь fallback поисковиков (SQLite FTS5 snapshot)."""
    return {"sqlite_fts5": _sqlite_fts5_search}
