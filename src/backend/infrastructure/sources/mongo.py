"""S106 W4 - MongoSource: MongoDB change-streams source (skeleton).

CDC-style event-streaming через MongoDB change streams: insert /
update / delete / replace на указанной коллекции. Требует MongoDB
replica set (change streams не работают на standalone).

S106 W4 scope: skeleton - Config dataclass + class skeleton + lazy
import motor. Реальный runtime-wiring (stream() async iterator,
resume-token, aggregation pipeline) - S106+ W5+ (multi-wave scope,
требует real Mongo replica set для testing).

DSL entry-point RouteBuilder.from_mongo(...) создаёт экземпляр для
smoke-валидации (S50 W2 pattern, как from_webdav).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.source import SourceKind

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ("MongoSource", "MongoChangeEvent", "MongoSourceConfig")


@dataclass(slots=True)
class MongoChangeEvent:
    """Входящее change-stream событие от MongoDB.

    Attributes:
        operation_type: insert / update / replace / delete / invalidate.
        database: Имя базы данных.
        collection: Имя коллекции.
        document_key: _id документа (или {"_id": ...} для delete).
        full_document: Полный документ (для insert/update/replace;
            для delete - None если не запрошен updateLookup).
        resume_token: _id change-stream документа (для resume при
            реконнекте).
        timestamp: Время события.
    """

    operation_type: str
    database: str
    collection: str
    document_key: dict[str, Any] | None = None
    full_document: dict[str, Any] | None = None
    resume_token: dict[str, Any] | None = None
    timestamp: "datetime | None" = None


@dataclass(slots=True)
class MongoSourceConfig:
    """Конфигурация MongoSource.

    Attributes:
        connection_url: MongoDB connection string.
        database: Имя базы данных (обязательно).
        collection: Имя коллекции (пустая строка = watch на уровне
            database, все коллекции).
        full_document_lookup: При True - для update-событий
            автоматически подгружается полная версия документа
            (fullDocument=updateLookup). Default False.
        pipeline: Опц. MongoDB aggregation pipeline для фильтрации
            change-stream events (server-side, до доставки клиенту).
    """

    connection_url: str
    database: str
    collection: str = ""
    full_document_lookup: bool = False
    pipeline: list[dict[str, Any]] | None = None


class MongoSource:
    """Источник событий из MongoDB change-streams (CDC pattern).

    Подключается к MongoDB, открывает change-stream на указанной
    коллекции (или на уровне database), эмитит MongoChangeEvent
    через async-iterator. Требует MongoDB replica set.

    Args:
        config: MongoSourceConfig с connection-параметрами.

    Raises:
        ValueError: При пустой connection_url или database.
    """

    kind: SourceKind = SourceKind.CDC

    def __init__(self, config: MongoSourceConfig) -> None:
        if not config.connection_url:
            raise ValueError("MongoSource: connection_url обязателен")
        if not config.database:
            raise ValueError("MongoSource: database обязателен")
        self._config = config
        self.source_id: str = f"mongo:{config.database}/{config.collection or '*'}"
        self._client: Any = None
        self._lock = asyncio.Lock()
        self._running = False

    @property
    def config(self) -> MongoSourceConfig:
        """Текущая конфигурация (read-only)."""
        return self._config

    async def stream(self) -> AsyncIterator[MongoChangeEvent]:
        """Async-iterator по Mongo change-stream events.

        S106 W4: skeleton. Реальная реализация (motor.watch() +
        resume-token + reconnect-loop) - S106+ W5+ (требует Mongo
        replica set для testing).
        """
        try:
            import motor.motor_asyncio  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return
        if False:  # pragma: no cover
            yield MongoChangeEvent(
                operation_type="insert",
                database=self._config.database,
                collection=self._config.collection or "",
            )

    async def stop(self) -> None:
        """Остановить change-stream и закрыть Mongo connection."""
        async with self._lock:
            self._running = False
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None
