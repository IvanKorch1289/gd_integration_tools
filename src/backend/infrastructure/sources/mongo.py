"""S106 W4 — ``MongoSource``: MongoDB change-streams source (real runtime).

CDC-style event-streaming через MongoDB change streams: insert /
update / delete / replace на указанной коллекции. Требует MongoDB
replica set (change streams не работают на standalone).

S107 W5: real runtime — ``stream()`` async-iterator с ``motor.watch()``
+ resume-token state + reconnect-loop. ``start()`` callback-обёртка
для Source-контракта. Resume token сохраняется между reconnect'ами
— при следующем ``watch(resume_after=...)`` клиент продолжает с
последнего обработанного event'а (exactly-once для single-consumer).

DSL entry-point ``RouteBuilder.from_mongo(...)`` создаёт экземпляр
для smoke-валидации (S50 W2 pattern, как ``from_webdav``).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.source import SourceEvent, SourceKind
from src.backend.core.logging import get_logger
if TYPE_CHECKING:
    pass

__all__ = ("MongoSource", "MongoChangeEvent", "MongoSourceConfig")

logger = get_logger("infrastructure.sources.mongo")


@dataclass(slots=True)
class MongoChangeEvent:
    """Входящее change-stream событие от MongoDB.

    Attributes:
        operation_type: insert / update / replace / delete / invalidate.
        database: Имя базы данных.
        collection: Имя коллекции.
        document_key: _id документа (или ``{"_id": ...}`` для delete).
        full_document: Полный документ (для insert/update/replace;
            для delete — ``None`` если не запрошен ``updateLookup``).
        resume_token: ``_id`` change-stream документа (для resume при
            реконнекте).
        timestamp: Время события.
    """

    operation_type: str
    database: str
    collection: str
    document_key: dict[str, Any] | None = None
    full_document: dict[str, Any] | None = None
    resume_token: dict[str, Any] | None = None
    timestamp: datetime = datetime.now(UTC)


@dataclass(slots=True)
class MongoSourceConfig:
    """Конфигурация MongoSource.

    Attributes:
        connection_url: MongoDB connection string.
        database: Имя базы данных (обязательно).
        collection: Имя коллекции (пустая строка = watch на уровне
            database, все коллекции).
        full_document_lookup: При ``True`` — для update-событий
            автоматически подгружается полная версия документа
            (``fullDocument=updateLookup``). Default ``False``.
        pipeline: Опц. MongoDB aggregation pipeline для фильтрации
            change-stream events (server-side, до доставки клиенту).
        max_reconnect_attempts: Макс. попыток reconnect при обрыве
            (0 = infinite). Default: 5.
        reconnect_delay_seconds: Задержка между попытками reconnect.
            Default: 1.0.
    """

    connection_url: str
    database: str
    collection: str = ""
    full_document_lookup: bool = False
    pipeline: list[dict[str, Any]] | None = None
    max_reconnect_attempts: int = 5
    reconnect_delay_seconds: float = 1.0


class MongoSource:
    """Источник событий из MongoDB change-streams (CDC pattern).

    Подключается к MongoDB, открывает change-stream на указанной
    коллекции (или на уровне database), эмитит
    :class:`MongoChangeEvent` через async-iterator. Требует MongoDB
    replica set.

    Resume-token: последний успешно обработанный ``_id`` change-stream
    документа сохраняется в ``self._resume_token``. При reconnect'е
    используется ``watch(resume_after=...)`` для exactly-once
    доставки (single-consumer).

    Args:
        config: :class:`MongoSourceConfig` с connection-параметрами.

    Raises:
        ValueError: При пустой ``connection_url`` или ``database``.
    """

    kind: SourceKind = SourceKind.CDC

    def __init__(self, config: MongoSourceConfig) -> None:
        if not config.connection_url:
            raise ValueError("MongoSource: connection_url обязателен")
        if not config.database:
            raise ValueError("MongoSource: database обязателен")
        if config.max_reconnect_attempts < 0:
            raise ValueError("MongoSource: max_reconnect_attempts >= 0")
        if config.reconnect_delay_seconds < 0:
            raise ValueError("MongoSource: reconnect_delay_seconds >= 0")
        self._config = config
        self.source_id: str = f"mongo:{config.database}/{config.collection or '*'}"
        self._client: Any = None
        self._lock = asyncio.Lock()
        self._running = False
        self._resume_token: dict[str, Any] | None = None

    @property
    def config(self) -> MongoSourceConfig:
        """Текущая конфигурация (read-only)."""
        return self._config

    @property
    def resume_token(self) -> dict[str, Any] | None:
        """Последний обработанный resume-token (``None`` до первого event)."""
        return self._resume_token

    async def stream(self) -> AsyncIterator[MongoChangeEvent]:
        """Async-iterator по Mongo change-stream events с reconnect-loop.

        Алгоритм (S107 W5):

        1. Lazy import ``motor`` (raise ImportError если не установлен);
        2. ``AsyncIOMotorClient(connection_url)`` (reusable client);
        3. ``db.watch(pipeline=..., resume_after=resume_token, ...)``
           (change-stream; ``resume_after`` — для continue after
           reconnect);
        4. While running: yield :class:`MongoChangeEvent` per change;
        5. На ошибке: ``asyncio.sleep(reconnect_delay)`` + retry open
           (max ``max_reconnect_attempts`` попыток; 0 = infinite).
        6. ``finally``: ``await stream.close()`` + ``client.close()``.

        Yields:
            :class:`MongoChangeEvent` для каждого change-event.

        Raises:
            ImportError: ``motor`` не установлен.
            RuntimeError: max reconnect attempts exhausted.
        """
        try:
            import motor.motor_asyncio  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "motor not installed. Add 'motor>=3.3' to dependencies "
                "(S3 Wave 3 cutover). For now: pip install motor."
            ) from exc

        async with self._lock:
            if self._client is not None:
                raise RuntimeError(
                    f"MongoSource(database={self._config.database!r}, "
                    f"collection={self._config.collection!r}) уже запущен"
                )
            self._client = None
            self._running = True

        reconnect_attempts = 0
        try:
            while self._running:
                try:
                    client = motor.motor_asyncio.AsyncIOMotorClient(  # type: ignore[attr-defined]
                        self._config.connection_url
                    )
                    db = client[self._config.database]
                    async with self._lock:
                        self._client = client

                    logger.info(
                        "MongoSource: подключён к %s, db=%s, coll=%s",
                        self._config.connection_url,
                        self._config.database,
                        self._config.collection or "*",
                    )

                    # Открываем change-stream. resume_after используется
                    # если уже был сохранён token от прошлой сессии.
                    watch_kwargs: dict[str, Any] = {}
                    if self._config.full_document_lookup:
                        watch_kwargs["full_document"] = "updateLookup"
                    if self._config.pipeline:
                        watch_kwargs["pipeline"] = self._config.pipeline
                    if self._resume_token is not None:
                        watch_kwargs["resume_after"] = self._resume_token

                    if self._config.collection:
                        change_stream = db[self._config.collection].watch(
                            **watch_kwargs
                        )
                    else:
                        change_stream = db.watch(**watch_kwargs)

                    try:
                        while self._running:
                            try:
                                change = await change_stream.next()
                            except Exception as fetch_exc:
                                # StopIteration / cursor closed — нормально
                                logger.debug(
                                    "MongoSource.next() ended (db=%s): %s",
                                    self._config.database,
                                    fetch_exc,
                                )
                                self._running = False
                                break

                            if change is None:
                                # No more docs (cursor closed) — естественное
                                # завершение change-stream, останавливаем и
                                # outer loop, не reconnect (избегаем spin-loop).
                                self._running = False
                                break

                            # Извлекаем resume-token
                            token = change.get("_id")
                            if token is not None:
                                self._resume_token = token

                            yield MongoChangeEvent(
                                operation_type=change.get("operationType", "unknown"),
                                database=self._config.database,
                                collection=change.get("ns", {}).get(
                                    "coll", self._config.collection
                                )
                                or "",
                                document_key=change.get("documentKey"),
                                full_document=change.get("fullDocument"),
                                resume_token=token,
                                timestamp=datetime.now(UTC),
                            )
                    finally:
                        try:
                            await change_stream.close()
                        except Exception as exc:
                            logger.debug(
                                "MongoSource: change_stream.close error: %s", exc
                            )

                    # Reset attempts на успешном завершении цикла.
                    # Если cursor закрылся сам (server-side end) — стоп,
                    # не переоткрываем (избегаем spin-loop).
                    if not self._running:
                        break

                except Exception as conn_exc:
                    logger.warning(
                        "MongoSource: connection error (attempt=%d): %s",
                        reconnect_attempts + 1,
                        conn_exc,
                    )
                    if self._config.max_reconnect_attempts and (
                        reconnect_attempts >= self._config.max_reconnect_attempts
                    ):
                        raise RuntimeError(
                            f"MongoSource: max reconnect attempts "
                            f"({self._config.max_reconnect_attempts}) "
                            f"exhausted"
                        ) from conn_exc
                    reconnect_attempts += 1
                    await asyncio.sleep(self._config.reconnect_delay_seconds)
        except GeneratorExit:
            logger.debug("MongoSource: iterator закрыт (db=%s)", self._config.database)
        finally:
            self._running = False
            await self._close()

    async def start(self, on_event: Any) -> None:
        """Запускает приём событий через callback (Source-контракт).

        Каждое change-event конвертируется в :class:`SourceEvent` и
        передаётся в ``on_event``. Callback-ошибки логируются, но
        не прерывают итерацию.

        Args:
            on_event: Async-callback, вызываемый на каждое событие.
        """
        async for change in self.stream():
            event = SourceEvent(
                source_id=self.source_id,
                kind=self.kind,
                payload=change.full_document or change.document_key or {},
                event_time=change.timestamp,
                metadata={
                    "operation_type": change.operation_type,
                    "database": change.database,
                    "collection": change.collection,
                    "resume_token": change.resume_token,
                },
            )
            try:
                await on_event(event)
            except Exception as exc:
                logger.error(
                    "MongoSource on_event failed (db=%s): %s",
                    self._config.database,
                    exc,
                )

    async def stop(self) -> None:
        """Корректно останавливает источник (close change-stream + client)."""
        self._running = False
        await self._close()

    async def health(self) -> bool:
        """Быстрая проверка: client подключён (ping) или ещё ни разу не было connect."""
        async with self._lock:
            client = self._client
        if client is None:
            return False
        try:
            # motor: client.admin.command("ping") — async-ping без полного query
            await client.admin.command("ping")  # type: ignore[attr-defined]
        except Exception:
            return False
        return True

    async def _close(self) -> None:
        """Закрывает Mongo client если открыт."""
        async with self._lock:
            client = self._client
            self._client = None
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                logger.debug("MongoSource close error: %s", exc)
