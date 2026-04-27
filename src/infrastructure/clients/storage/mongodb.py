"""Async MongoDB client через motor."""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("MongoDBClient", "get_mongo_client")

logger = logging.getLogger(__name__)


class MongoDBClient:
    """Асинхронный MongoDB клиент через motor.

    Implements ManagedResource pattern (start/stop + health check).
    """

    def __init__(
        self,
        connection_url: str = "mongodb://localhost:27017",
        database: str = "gd_integration",
        max_pool_size: int = 50,
        min_pool_size: int = 5,
    ) -> None:
        self._url = connection_url
        self._database_name = database
        self._max_pool = max_pool_size
        self._min_pool = min_pool_size
        self._client: Any = None
        self._db: Any = None

    async def start(self) -> None:
        from motor.motor_asyncio import AsyncIOMotorClient

        self._client = AsyncIOMotorClient(
            self._url, maxPoolSize=self._max_pool, minPoolSize=self._min_pool
        )
        self._db = self._client[self._database_name]
        await self._client.admin.command("ping")
        logger.info("MongoDB connected: %s/%s", self._url, self._database_name)

    async def stop(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("MongoDB disconnected")

    @property
    def db(self) -> Any:
        if self._db is None:
            raise RuntimeError("MongoDBClient not started")
        return self._db

    def collection(self, name: str) -> Any:
        return self.db[name]

    async def find(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        projection: dict[str, Any] | None = None,
        limit: int = 100,
        skip: int = 0,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self.db[collection].find(query or {}, projection)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.skip(skip).limit(limit)
        return [doc async for doc in cursor]

    async def find_one(
        self, collection: str, query: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self.db[collection].find_one(query)

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        result = await self.db[collection].insert_one(document)
        return str(result.inserted_id)

    async def insert_many(
        self, collection: str, documents: list[dict[str, Any]]
    ) -> list[str]:
        result = await self.db[collection].insert_many(documents)
        return [str(id_) for id_ in result.inserted_ids]

    async def update_one(
        self,
        collection: str,
        query: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> int:
        result = await self.db[collection].update_one(
            query, {"$set": update}, upsert=upsert
        )
        return result.modified_count

    async def delete_one(self, collection: str, query: dict[str, Any]) -> int:
        result = await self.db[collection].delete_one(query)
        return result.deleted_count

    async def aggregate(
        self, collection: str, pipeline: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cursor = self.db[collection].aggregate(pipeline)
        return [doc async for doc in cursor]

    async def count(self, collection: str, query: dict[str, Any] | None = None) -> int:
        return await self.db[collection].count_documents(query or {})

    async def ping(self) -> bool:
        try:
            if self._client is None:
                return False
            await self._client.admin.command("ping")
            return True
        except ConnectionError, TimeoutError, OSError:
            return False


def _create_mongo_client() -> MongoDBClient:
    from src.core.config.settings import settings

    return MongoDBClient(
        connection_url=settings.mongo.connection_url, database=settings.mongo.database
    )


from src.infrastructure.application.di import app_state_singleton


@app_state_singleton("mongo_client", _create_mongo_client)
def get_mongo_client() -> MongoDBClient:
    """Возвращает MongoDBClient из app.state или lazy-init fallback."""
