"""``SqliteFTS5Search`` — fallback ``SearchClient`` на SQLite FTS5 (Wave 21.3c).

Используется в dev_light, где Elasticsearch недоступен. SQLite FTS5
поддерживает full-text search в одиночной библиотеке без сервера.

Структура (одна виртуальная таблица на index):

    CREATE VIRTUAL TABLE idx_<name> USING fts5(
        doc_id UNINDEXED,
        body              -- JSON-encoded полный документ
    );

``index_document`` парсит ``document`` → JSON-кодирует → INSERT.
``search`` выполняет ``MATCH``-запрос против всех полей. Маппинги
игнорируются (FTS5 индексирует все колонки).

Ограничения:
- ``aggregate`` возвращает упрощённый count-агрегат (без bucket-логики);
- сортировка по ``sort`` поддерживается только для одного поля
  (top-level ключ документа).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import aiosqlite

__all__ = ("SqliteFTS5Search",)

_INDEX_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class SqliteFTS5Search:
    """Реализует контракт :class:`src.core.interfaces.SearchClient`."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._known: set[str] = set()

    # ─────────────────────── SearchClient API ───────────────────────

    async def index_document(
        self,
        index: str,
        document: dict[str, Any],
        doc_id: str | None = None,
    ) -> dict[str, Any]:
        table = await self._ensure_index(index)
        doc_id = doc_id or document.get("id") or document.get("_id") or _hash_doc(document)
        body = json.dumps(document, ensure_ascii=False, default=str)
        # Имя таблицы валидируется в _ensure_index регуляркой — S608 false positive.
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                f"DELETE FROM {table} WHERE doc_id = ?",  # noqa: S608
                (doc_id,),
            )
            await db.execute(
                f"INSERT INTO {table} (doc_id, body) VALUES (?, ?)",  # noqa: S608
                (doc_id, body),
            )
            await db.commit()
        return {"_id": doc_id, "result": "indexed"}

    async def bulk_index(
        self,
        index: str,
        documents: list[dict[str, Any]],
        id_field: str | None = None,
    ) -> dict[str, Any]:
        for d in documents:
            doc_id = d.get(id_field) if id_field else None
            await self.index_document(index, d, doc_id=doc_id)
        return {"indexed": len(documents)}

    async def search(
        self,
        index: str,
        query: str | dict[str, Any],
        size: int = 10,
        from_: int = 0,
        sort: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        table = await self._ensure_index(index)
        match = self._build_match(query)
        # Имя таблицы валидируется в _ensure_index — S608 false positive.
        sql = f"SELECT doc_id, body FROM {table}"  # noqa: S608
        params: list[Any] = []
        if match:
            sql += f" WHERE {table} MATCH ?"
            params.append(match)
        sql += " LIMIT ? OFFSET ?"
        params.extend([size, from_])
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(sql, tuple(params))
            rows = await cursor.fetchall()
        results = [json.loads(body) for _, body in rows]
        if sort:
            sort_key, sort_dir = self._parse_sort(sort[0])
            results.sort(
                key=lambda d: d.get(sort_key, 0), reverse=(sort_dir == "desc")
            )
        return results

    async def aggregate(
        self,
        index: str,
        aggs: dict[str, Any],
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        table = await self._ensure_index(index)
        match = self._build_match(query) if query else ""
        sql = f"SELECT COUNT(*) FROM {table}"  # noqa: S608
        params: list[Any] = []
        if match:
            sql += f" WHERE {table} MATCH ?"
            params.append(match)
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(sql, tuple(params))
            row = await cursor.fetchone()
        return {
            "aggregations": {name: {"value": int(row[0]) if row else 0} for name in aggs}
        }

    async def delete_document(self, index: str, doc_id: str) -> bool:
        table = await self._ensure_index(index)
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                f"DELETE FROM {table} WHERE doc_id = ?",  # noqa: S608
                (doc_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def create_index(
        self, index: str, mappings: dict[str, Any] | None = None
    ) -> None:
        del mappings  # FTS5 без маппингов — всё индексируется как текст
        await self._ensure_index(index)

    async def ping(self) -> bool:
        try:
            async with aiosqlite.connect(self._path) as db:
                await db.execute("SELECT 1")
            return True
        except aiosqlite.Error:
            return False

    # ─────────────────────── Internals ───────────────────────

    async def _ensure_index(self, index: str) -> str:
        if not _INDEX_RE.match(index):
            raise ValueError(
                f"Некорректное имя индекса '{index}': допустимы [A-Za-z_][A-Za-z0-9_]*"
            )
        table = f"idx_{index}"
        if table in self._known:
            return table
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} "
                "USING fts5(doc_id UNINDEXED, body)"
            )
            await db.commit()
        self._known.add(table)
        return table

    @staticmethod
    def _build_match(query: str | dict[str, Any] | None) -> str:
        """Преобразует ES-подобный query в FTS5 MATCH-выражение."""
        if not query:
            return ""
        if isinstance(query, str):
            return query
        if isinstance(query, dict):
            # Минимальная поддержка ``{"match": {"field": "value"}}``.
            match = query.get("match")
            if isinstance(match, dict):
                values = [str(v) for v in match.values() if v]
                return " ".join(values)
            # ``{"query_string": {"query": "..."}}`` или просто ``{"q": "..."}``.
            qs = query.get("query_string", {}).get("query") or query.get("q")
            if qs:
                return str(qs)
        return ""

    @staticmethod
    def _parse_sort(sort_item: dict[str, Any]) -> tuple[str, str]:
        # ``{"field": "desc"}`` или ``{"field": {"order": "desc"}}``.
        for field, spec in sort_item.items():
            if isinstance(spec, dict):
                return field, str(spec.get("order", "asc")).lower()
            return field, str(spec).lower()
        return "_score", "desc"


def _hash_doc(doc: dict[str, Any]) -> str:
    """Стабильный hash от документа (для авто-генерации doc_id)."""
    import hashlib

    # sha256 используется не для security, а для стабильного doc_id
    # (sha1 триггерил ruff S324 при том же назначении).
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
