"""Wiring W26.4: MongoDB → PostgreSQL JSONB.

Контракт callable: ``async def mongo_find_one(collection: str, query: dict) -> dict | None``.

PostgreSQL fallback использует таблицу ``app_doc_store`` с колонкой
``data JSONB`` для имитации Mongo-like хранилища; запросы идут через
PG-операторы ``->`` / ``@>``. Отлично работает для read-fallback'а;
write-операции в fallback-режиме блокируются на middleware-уровне.

Mongo-only фичи (aggregation pipelines, change streams, GridFS) не
поддерживаются в fallback'е — соответствующие операции должны явно
fail при OPEN-breaker'е.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import orjson

__all__ = ("MongoFindCallable", "build_mongo_fallbacks", "build_mongo_primary")

logger = logging.getLogger(__name__)

MongoFindCallable = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]


async def _mongo_find_one(
    collection: str, query: dict[str, Any]
) -> dict[str, Any] | None:
    from src.backend.infrastructure.clients.storage.mongodb import get_mongo_client

    client = get_mongo_client()
    db = client.get_database()  # имя берётся из connection settings
    coll = db[collection]
    return await coll.find_one(query)


async def _pg_jsonb_find_one(
    collection: str, query: dict[str, Any]
) -> dict[str, Any] | None:
    from sqlalchemy import text

    from src.backend.infrastructure.database.database import get_db_session

    async with get_db_session() as session:
        result = await session.execute(
            text(
                "SELECT data FROM app_doc_store WHERE collection = :coll "
                "AND data @> :q ::jsonb LIMIT 1"
            ),
            {"coll": collection, "q": orjson.dumps(query).decode()},
        )
        row = result.first()
        return row[0] if row else None


def build_mongo_primary() -> MongoFindCallable:
    return _mongo_find_one


def build_mongo_fallbacks() -> dict[str, MongoFindCallable]:
    return {"pg_jsonb": _pg_jsonb_find_one}
