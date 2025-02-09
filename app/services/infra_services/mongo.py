from bson import ObjectId
from typing import Any, Dict, List, Optional

from app.infra.db.mongo import MongoClient, mongo_client


__all__ = (
    "MongoService",
    "mongo_service",
)


class MongoService:
    def __init__(self, client: MongoClient):
        self.client = client

    async def insert_one(
        self, collection: str, document: Dict[str, Any]
    ) -> Optional[ObjectId]:
        async with self.client.get_connection() as db:
            result = await db[collection].insert_one(document)
            return result.inserted_id

    async def find_one(
        self, collection: str, query: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        async with self.client.get_connection() as db:
            return await db[collection].find_one(query)

    async def find_all(
        self, collection: str, query: Dict[str, Any] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        async with self.client.get_connection() as db:
            cursor = db[collection].find(query or {}).limit(limit)
            return await cursor.to_list(length=limit)

    async def update_one(
        self,
        collection: str,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
    ) -> int:
        async with self.client.get_connection() as db:
            result = await db[collection].update_one(
                query, {"$set": update_data}
            )
            return result.modified_count

    async def delete_one(self, collection: str, query: Dict[str, Any]) -> int:
        async with self.client.get_connection() as db:
            result = await db[collection].delete_one(query)
            return result.deleted_count


mongo_service = MongoService(client=mongo_client)
