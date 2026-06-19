"""``SqliteDocStore`` — SQLite-based fallback DocStoreBackend (Wave 21.3c).

Структура таблицы (одна на namespace, создаётся лениво):

    CREATE TABLE doc_<namespace> (
        doc_id TEXT PRIMARY KEY,
        body   TEXT NOT NULL  -- JSON-encoded
    );

Фильтры применяются на python-стороне (для простоты — на dev-объёмах
до 10^4 документов это нормально). Для production остаются Mongo-репы.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import aiosqlite
import orjson

from src.backend.core.interfaces.doc_store import DocStoreBackend

__all__ = ("SqliteDocStore",)

_NAMESPACE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class SqliteDocStore(DocStoreBackend):
    """SQLite-backed document store. ``path`` — путь к sqlite3-файлу."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._known_namespaces: set[str] = set()

    # ─────────────────────── Public API ───────────────────────

    async def insert(
        self, namespace: str, doc: dict[str, Any], *, doc_id: str | None = None
    ) -> str:
        """Insert or replace a document.

        Args:
            namespace: Document namespace (table name).
            doc: Document data.
            doc_id: Optional document ID (auto-generated if None).

        Returns:
            Document ID.
        """
        table = await self._ensure_namespace(namespace)
        if doc_id is None:
            doc_id = str(uuid.uuid4())
        body = orjson.dumps(doc, default=str).decode()
        # Имя таблицы валидируется в _ensure_namespace регуляркой,
        # SQL-injection невозможен (S608 — false positive).
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                f"INSERT OR REPLACE INTO {table} (doc_id, body) VALUES (?, ?)",  # noqa: S608  # internal query with controlled parameters
                (doc_id, body),
            )
            await db.commit()
        return doc_id

    async def get(self, namespace: str, doc_id: str) -> dict[str, Any] | None:
        """Get a document by ID.

        Args:
            namespace: Document namespace.
            doc_id: Document ID.

        Returns:
            Document dict or None if not found.
        """
        table = await self._ensure_namespace(namespace)
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                f"SELECT body FROM {table} WHERE doc_id = ?",  # noqa: S608  # internal query with controlled parameters
                (doc_id,),
            )
            row = await cursor.fetchone()
        return orjson.loads(row[0]) if row else None

    async def update(self, namespace: str, doc_id: str, patch: dict[str, Any]) -> bool:
        """Update a document with partial patch.

        Args:
            namespace: Document namespace.
            doc_id: Document ID.
            patch: Fields to update.

        Returns:
            True if updated, False if not found.
        """
        existing = await self.get(namespace, doc_id)
        if existing is None:
            return False
        existing.update(patch)
        await self.insert(namespace, existing, doc_id=doc_id)
        return True

    async def delete(self, namespace: str, doc_id: str) -> bool:
        """Delete a document by ID.

        Args:
            namespace: Document namespace.
            doc_id: Document ID.

        Returns:
            True if deleted, False if not found.
        """
        table = await self._ensure_namespace(namespace)
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                f"DELETE FROM {table} WHERE doc_id = ?",  # noqa: S608  # internal query with controlled parameters
                (doc_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def find(
        self,
        namespace: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Find documents with optional filters.

        Args:
            namespace: Document namespace.
            filters: Optional field filters.
            limit: Maximum results.
            offset: Results offset.

        Returns:
            List of matching documents.
        """
        table = await self._ensure_namespace(namespace)
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                f"SELECT body FROM {table} ORDER BY doc_id LIMIT ? OFFSET ?",  # noqa: S608  # internal query with controlled parameters
                (limit if filters is None else 1_000_000, offset),
            )
            rows = await cursor.fetchall()
        docs = [orjson.loads(row[0]) for row in rows]
        if filters:
            docs = [d for d in docs if all(d.get(k) == v for k, v in filters.items())]
            docs = docs[:limit]
        return docs

    async def count(self, namespace: str, filters: dict[str, Any] | None = None) -> int:
        """Count documents with optional filters.

        Args:
            namespace: Document namespace.
            filters: Optional field filters.

        Returns:
            Document count.
        """
        if filters is None:
            table = await self._ensure_namespace(namespace)
            async with aiosqlite.connect(self._path) as db:
                cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608  # internal query with controlled parameters
                row = await cursor.fetchone()
            return int(row[0]) if row else 0
        # С фильтрами — линейный подсчёт через find().
        return len(await self.find(namespace, filters=filters, limit=10**9))

    # ─────────────────────── Internals ───────────────────────

    async def _ensure_namespace(self, namespace: str) -> str:
        # Защита от SQL-injection через имя namespace: жёсткий whitelist.
        if not _NAMESPACE_RE.match(namespace):
            raise ValueError(
                f"Некорректный namespace '{namespace}': допустимы [A-Za-z_][A-Za-z0-9_]*"
            )
        table = f"doc_{namespace}"
        if table in self._known_namespaces:
            return table
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ("
                "doc_id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            await db.commit()
        self._known_namespaces.add(table)
        return table
