"""Async MongoDB client через ``pymongo.AsyncMongoClient`` (S31 Task 7).

S31 Task 7: мигрировано с ``motor.motor_asyncio.AsyncIOMotorClient`` на
``pymongo.AsyncMongoClient`` (native async, available in PyMongo 4.9+).
Motor is in maintenance mode per MongoDB official guidance; PyMongo native
async is the recommended path.

API совместим на ~95% — ``find``, ``insert_one``, ``update_many``, и т.д.
работают идентично. Различия в инициализации (см. ``start()``).
"""

from __future__ import annotations

import inspect
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.resilience.connector_resilience import resilient

__all__ = ("MongoDBClient", "get_mongo_client")

logger = get_logger(__name__)


class MongoDBClient:
    """Асинхронный MongoDB клиент через ``pymongo.AsyncMongoClient``.

    Implements ManagedResource pattern (start/stop + health check).
    S181: добавлен Circuit Breaker + Retry через :func:`resilient` decorator
    для критических операций (find, insert, update, delete).
    S31 Task 7: мигрировано с motor на pymongo native async.
    """

    def __init__(
        self,
        connection_url: str = "mongodb://localhost:27017",
        database: str = "gd_integration",
        max_pool_size: int = 50,
        min_pool_size: int = 5,
        tls_enabled: bool = False,
        tls_ca_file: str | None = None,
    ) -> None:
        # S182: TLS/SSL support (security hardening для банковской шины)
        self._tls_enabled = tls_enabled
        self._tls_ca_file = tls_ca_file
        self._url = connection_url
        self._database_name = database
        self._max_pool = max_pool_size
        self._min_pool = min_pool_size
        self._client: Any = None
        self._db: Any = None

    async def start(self) -> None:
        """Start the MongoDB client and create connection pool.

        Uses :class:`pymongo.AsyncMongoClient` (PyMongo >= 4.9). Previously
        used ``motor.motor_asyncio.AsyncIOMotorClient`` (deprecated upstream).
        """
        # S182: TLS configuration
        tls_options: dict[str, Any] | None = None
        if self._tls_enabled:
            tls_options = {"tls": True}
            if self._tls_ca_file:
                tls_options["tlsCAFile"] = self._tls_ca_file
        client_kwargs: dict[str, Any] = {
            "maxPoolSize": self._max_pool,
            "minPoolSize": self._min_pool,
        }
        if tls_options:
            client_kwargs.update(tls_options)
        # S31 Task 7: native async client (PyMongo 4.9+). No wrapper layer.
        from pymongo import AsyncMongoClient

        self._client = AsyncMongoClient(self._url, **client_kwargs)
        self._db = self._client[self._database_name]
        await self._client.admin.command("ping")
        logger.info(
            "MongoDB connected (pymongo.AsyncMongoClient): %s/%s",
            self._url,
            self._database_name,
        )

    async def stop(self) -> None:
        """Stop the MongoDB client and close connections."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("MongoDB disconnected")

    @property
    def db(self) -> Any:
        """Get MongoDB database instance.

        Returns:
            Database instance.

        Raises:
            RuntimeError: If client not started.

        """
        if self._db is None:
            raise RuntimeError("MongoDBClient not started")
        return self._db

    def collection(self, name: str) -> Any:
        """Get MongoDB collection by name.

        Args:
            name: Collection name.

        Returns:
            Collection instance.

        """
        return self.db[name]

    @resilient(name="mongodb_find", max_attempts=3)
    async def find(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        projection: dict[str, Any] | None = None,
        limit: int = 100,
        skip: int = 0,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents in collection.

        Args:
            collection: Collection name.
            query: Query filter.
            projection: Field projection.
            limit: Max results.
            skip: Results offset.
            sort: Sort specification.

        Returns:
            List of matching documents.

        Note:
            S181: Circuit Breaker "mongodb_find" + 3 retry attempts.

        """
        cursor = self.db[collection].find(query or {}, projection)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.skip(skip).limit(limit)
        return [doc async for doc in cursor]

    @resilient(name="mongodb_find_one", max_attempts=3)
    async def find_one(
        self, collection: str, query: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Find single document in collection.

        Args:
            collection: Collection name.
            query: Query filter.

        Returns:
            Document or None if not found.

        """
        return await self.db[collection].find_one(query)

    @resilient(name="mongodb_insert", max_attempts=3)
    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """Insert single document.

        Args:
            collection: Collection name.
            document: Document to insert.

        Returns:
            Inserted document ID.

        """
        result = await self.db[collection].insert_one(document)
        return str(result.inserted_id)

    @resilient(name="mongodb_insert_many", max_attempts=3)
    async def insert_many(
        self,
        collection: str,
        documents: list[dict[str, Any]],
        *,
        ordered: bool = True,
        batch_size: int = 1000,
    ) -> list[str]:
        """Insert multiple documents в батчах (S182 I-4.4).

        S182: добавлен ``batch_size`` и ``ordered`` параметры.
        При ``batch_size > 0`` — chunks для защиты от OOM при больших bulk-операциях.

        Args:
            collection: Collection name.
            documents: Documents to insert.
            ordered: Если True — остановка на первой ошибке (default).
            batch_size: Макс. документов в одном bulk insert (default 1000).

        Returns:
            List of inserted document IDs.

        Note:
            Circuit Breaker "mongodb_insert_many" + 3 retry attempts.

        """
        if not documents:
            return []

        all_ids: list[str] = []
        if batch_size <= 0 or len(documents) <= batch_size:
            result = await self.db[collection].insert_many(documents, ordered=ordered)
            return [str(id_) for id_ in result.inserted_ids]

        # Chunked insert
        for i in range(0, len(documents), batch_size):
            chunk = documents[i : i + batch_size]
            result = await self.db[collection].insert_many(chunk, ordered=ordered)
            all_ids.extend(str(id_) for id_ in result.inserted_ids)
        return all_ids

    @resilient(name="mongodb_update_many", max_attempts=3)
    async def update_many(
        self, collection: str, query: dict[str, Any], update: dict[str, Any]
    ) -> int:
        """Update multiple documents matching query.

        Args:
            collection: Collection name.
            query: Query filter.
            update: Update operations (например, ``{"$set": {...}}``).

        Returns:
            Number of modified documents.

        Note:
            Circuit Breaker "mongodb_update_many" + 3 retry attempts.

        """
        result = await self.db[collection].update_many(query, update)
        return result.modified_count

    @resilient(name="mongodb_delete_many", max_attempts=3)
    async def delete_many(self, collection: str, query: dict[str, Any]) -> int:
        """Delete multiple documents matching query.

        Args:
            collection: Collection name.
            query: Query filter.

        Returns:
            Number of deleted documents.

        """
        result = await self.db[collection].delete_many(query)
        return result.deleted_count

    async def update_one(
        self,
        collection: str,
        query: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> int:
        """Update single document.

        Args:
            collection: Collection name.
            query: Query filter.
            update: Update operations.
            upsert: Insert if not exists.

        Returns:
            Number of modified documents.

        """
        result = await self.db[collection].update_one(
            query, {"$set": update}, upsert=upsert
        )
        return result.modified_count

    async def delete_one(self, collection: str, query: dict[str, Any]) -> int:
        """Delete single document.

        Args:
            collection: Collection name.
            query: Query filter.

        Returns:
            Number of deleted documents.

        """
        result = await self.db[collection].delete_one(query)
        return result.deleted_count

    async def aggregate(
        self, collection: str, pipeline: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Run aggregation pipeline.

        Args:
            collection: Collection name.
            pipeline: Aggregation pipeline stages.

        Returns:
            List of aggregation results.

        """
        cursor = self.db[collection].aggregate(pipeline)
        return [doc async for doc in cursor]

    async def count(self, collection: str, query: dict[str, Any] | None = None) -> int:
        """Count documents matching query.

        Args:
            collection: Collection name.
            query: Query filter.

        Returns:
            Document count.

        """
        return await self.db[collection].count_documents(query or {})

    async def ping(self) -> bool:
        """Check MongoDB connection health.

        Returns:
            True if connected.

        """
        try:
            if self._client is None:
                return False
            await self._client.admin.command("ping")
            return True
        except ConnectionError, TimeoutError, OSError:
            return False

    async def health_check(self, *, mode: str = "fast") -> dict[str, Any]:
        """Health probe для HealthAggregator (Sprint 170 M2 Phase 1)."""
        try:
            import time

            start = time.monotonic()
            ping = getattr(self, "ping", None)
            if ping is None:
                return {"status": "ok", "latency_ms": 0.0, "error": None}
            result = await ping() if inspect.iscoroutinefunction(ping) else ping()
            return {
                "status": "ok" if result else "down",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
                "error": None,
            }
        except Exception as exc:
            return {"status": "down", "error": str(exc)}


def _create_mongo_client() -> MongoDBClient:
    from src.backend.core.config.settings import settings

    return MongoDBClient(
        connection_url=settings.mongo.connection_string, database=settings.mongo.name
    )


from src.backend.core.di import app_state_singleton


@app_state_singleton("mongo_client", _create_mongo_client)
def get_mongo_client() -> MongoDBClient:  # type: ignore[empty-body]
    """Возвращает MongoDBClient из app.state или lazy-init fallback."""
