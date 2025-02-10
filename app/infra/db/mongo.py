from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure, PyMongoError

from app.config.settings import MongoConnectionSettings, settings
from app.utils.logging_service import db_logger


__all__ = (
    "MongoClient",
    "mongo_client",
)


class MongoClient:
    def __init__(self, settings: MongoConnectionSettings):
        self.settings = settings
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None

    async def connect(self) -> None:
        """Установка соединения с пулом подключений"""
        try:
            self.client = AsyncIOMotorClient(
                self.settings.connection_string,
                serverSelectionTimeoutMS=self.settings.timeout,
                maxPoolSize=self.settings.max_pool_size,
                minPoolSize=self.settings.min_pool_size,
            )
            await self.client.admin.command("ping")
            self.db = self.client[self.settings.name]
            db_logger.info("Successfully connected to MongoDB")

        except ConnectionFailure as exc:
            db_logger.critical("MongoDB connection failed", exc_info=True)
            raise RuntimeError("MongoDB connection failed") from exc

    async def close(self) -> None:
        """Закрытие соединений"""
        if self.client:
            await self.client.wait_closed()
            db_logger.info("MongoDB connection closed")

    @asynccontextmanager
    async def get_connection(
        self,
    ) -> AsyncGenerator[AsyncIOMotorDatabase, None]:
        """Асинхронный контекстный менеджер"""
        try:
            yield self.db
        except PyMongoError:
            db_logger.error("MongoDB operation failed", exc_info=True)
            raise


mongo_client = MongoClient(settings=settings.mongo)
