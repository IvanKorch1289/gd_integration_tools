from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, AsyncIterator, Dict, List, Tuple

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.config.settings import RedisSettings, settings
from app.utils.decorators.singleton import singleton


__all__ = ("redis_client", "RedisClient")


@singleton
class RedisClient:
    """Асинхронный клиент Redis с поддержкой пула соединений и автоматическим переподключением.

    Attributes:
        settings: Настройки Redis.
        _client: Экземпляр асинхронного клиента Redis.
        _lock: Asyncio lock для потокобезопасной инициализации соединений.
        _connection_pool: Менеджер пула соединений Redis.
    """

    def __init__(self, settings: RedisSettings) -> None:
        """Инициализирует клиент Redis с настройками.

        Args:
            settings: Параметры конфигурации Redis.
        """
        import asyncio

        from app.utils.logging_service import redis_logger

        self._client: Redis | None = None
        self._lock = asyncio.Lock()
        self.settings = settings
        self._connection_pool: ConnectionPool | None = None
        self.logger = redis_logger

    async def _init_pool(self) -> None:
        """Инициализирует пул соединений Redis с заданными параметрами."""
        # Формируем URL для подключения к Redis с учетом SSL
        redis_scheme = "rediss" if self.settings.use_ssl else "redis"
        redis_url = (
            f"{redis_scheme}://{self.settings.host}:{self.settings.port}"
        )

        try:
            self._connection_pool = ConnectionPool.from_url(
                redis_url,
                db=self.settings.db_cache,
                password=self.settings.password or None,
                encoding=self.settings.encoding,
                socket_timeout=self.settings.socket_timeout,
                socket_connect_timeout=self.settings.socket_connect_timeout,
                socket_keepalive=self.settings.socket_keepalive,
                retry_on_timeout=self.settings.retry_on_timeout,
                max_connections=self.settings.max_connections,
                decode_responses=False,
                health_check_interval=self.settings.health_check_interval,
            )

            self._client = Redis(connection_pool=self._connection_pool)
            self.logger.info("Пул соединений Redis успешно инициализирован")
        except RedisError as exc:
            self.logger.error(
                f"Ошибка инициализации пула соединений: {str(exc)}",
                exc_info=True,
            )
            raise

    async def ensure_connected(self) -> None:
        """Обеспечивает активное соединение с использованием шаблона Double-Checked Locking."""
        if self._client and await self._client.ping():
            return

        async with self._lock:
            if not self._client or not await self._client.ping():
                await self._init_pool()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Redis]:
        """Асинхронный контекстный менеджер для работы с соединениями Redis.

        Yields:
            Redis: Активный экземпляр соединения Redis.

        Raises:
            RedisError: Если соединение не может быть установлено.
        """
        await self.ensure_connected()

        try:
            if not self._client:
                raise RedisError("Клиент Redis не инициализирован")
            yield self._client
        except (RedisError, ConnectionError, TimeoutError) as exc:
            self.logger.error(
                f"Ошибка соединения с Redis: {str(exc)}", exc_info=True
            )
            raise

    async def close(self) -> None:
        """Закрывает все соединения Redis и освобождает ресурсы."""
        if self._connection_pool:
            try:
                await self._connection_pool.disconnect()
                self.logger.info("Пул соединений Redis успешно закрыт")
            except Exception as exc:
                self.logger.error(
                    f"Ошибка при закрытии пула соединений: {str(exc)}",
                    exc_info=True,
                )
            finally:
                self._client = None
                self._connection_pool = None

    async def check_connection(self) -> bool:
        """Проверяет, активно ли соединение с Redis.

        Returns:
            bool: True, если соединение активно, иначе False.
        """
        try:
            async with self.connection() as conn:
                return await conn.ping()
        except RedisError:
            return False

    def reconnect_on_failure(self, func: Any) -> Any:
        """Декоратор для автоматического переподключения при сбоях соединения.

        Args:
            func: Метод, который нужно обернуть логикой переподключения.
        """

        @wraps(func)
        async def wrapper(
            self: "RedisClient", *args: Any, **kwargs: Any
        ) -> Any:
            try:
                return await func(self, *args, **kwargs)
            except (ConnectionError, TimeoutError, RedisError) as exc:
                self.logger.warning(
                    f"Переподключение из-за ошибки: {str(exc)}"
                )
                await self.ensure_connected()
                return await func(self, *args, **kwargs)

        return wrapper

    async def __aenter__(self) -> "RedisClient":
        """Точка входа для асинхронного контекстного менеджера."""
        await self.ensure_connected()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        """Точка выхода для асинхронного контекстного менеджера."""
        await self.close()

    @asynccontextmanager
    async def _switch_db_context(
        self, conn: Redis, target_db: int
    ) -> AsyncIterator[None]:
        """Контекстный менеджер для временного переключения БД.

        Args:
            conn: Экземпляр соединения Redis.
            target_db: Целевая база данных.

        Yields:
            None
        """
        await conn.execute_command("SELECT", target_db)
        try:
            yield
        finally:
            await conn.execute_command("SELECT", self.settings.db_cache)

    async def _stream_exists(self, stream_name: str) -> bool:
        """Проверяет существование стрима в Redis.

        Args:
            stream_name: Имя стрима.

        Returns:
            bool: True, если стрим существует, иначе False.
        """
        try:
            async with self.connection() as conn:
                async with self._switch_db_context(
                    conn, self.settings.db_queue
                ):
                    result = await conn.type(stream_name)
                    if result == b"stream":
                        return True
                    return False
        except Exception as exc:
            self.logger.error(
                f"Ошибка при проверке существования стрима {stream_name}: {str(exc)}",
                exc_info=True,
            )
            return False

    async def create_initial_streams(self) -> None:
        """Создает базовые стримы при инициализации клиента."""
        for stream in self.settings.streams:
            try:
                if not await self._stream_exists(stream["value"]):
                    await self._initialize_stream(stream["value"])
                    self.logger.info(
                        f"Стрим {stream['value']} успешно инициализирован"
                    )
            except Exception as exc:
                self.logger.error(
                    f"Не удалось инициализировать стрим {stream['value']}: {str(exc)}",
                    exc_info=True,
                )

    async def _initialize_stream(self, stream_name: str) -> None:
        """Инициализирует стрим с настройками из конфигурации.

        Args:
            stream_name: Имя стрима.
        """
        args = {}
        if self.settings.max_stream_len:
            args["maxlen"] = self.settings.max_stream_len
            args["approximate"] = self.settings.approximate_trimming_stream

        async with self.connection() as conn:
            async with self._switch_db_context(conn, self.settings.db_queue):
                # Создаем стрим с начальным сообщением
                init_id = await conn.xadd(
                    name=stream_name, fields={"__init__": "initial"}, **args
                )

                # Удаляем начальное сообщение
                await conn.xdel(stream_name, init_id)

                # Применяем политику удержания
                if self.settings.retention_hours_stream:
                    retention_ms = (
                        self.settings.retention_hours_stream * 3600 * 1000
                    )
                    minid = f"{int(datetime.now().timestamp() * 1000) - retention_ms}"
                    await conn.xtrim(
                        name=stream_name, minid=minid, approximate=True
                    )

    async def stream_publish(
        self,
        stream: str,
        data: Dict[str, Any],
        max_len: int | None = None,
        approximate: bool = True,
    ) -> str:
        """Публикует событие в стрим Redis.

        Args:
            stream: Имя целевого стрима.
            data: Словарь с данными события.
            max_len: Максимальная длина стрима (для обрезки).
            approximate: Использовать эффективную обрезку с приблизительной точностью.

        Returns:
            str: Идентификатор созданного события.

        Raises:
            RedisError: Если публикация не удалась.
        """
        try:
            async with self.connection() as conn:
                async with self._switch_db_context(
                    conn, self.settings.db_queue
                ):
                    args = {}
                    if max_len is not None:
                        args["maxlen"] = max_len
                        args["approximate"] = approximate

                    event_id = await conn.xadd(stream, data, id="*", **args)

                    self.logger.debug(
                        f"Событие опубликовано в {stream}: {event_id}"
                    )

                    return event_id
        except RedisError as exc:
            self.logger.error(
                f"Ошибка публикации в стрим: {str(exc)}", exc_info=True
            )
            raise

    async def stream_move(
        self,
        source_stream: str,
        dest_stream: str,
        event_id: str,
        additional_data: Dict[str, Any] | None = None,
    ) -> None:
        """Перемещает событие между стримами с возможностью добавления метаданных.

        Args:
            source_stream: Имя исходного стрима.
            dest_stream: Имя целевого стрима.
            event_id: Идентификатор события для перемещения.
            additional_data: Дополнительные данные для добавления к событию.

        Raises:
            RedisError: Если операция не удалась.
        """
        try:
            async with self.connection() as conn:
                async with self._switch_db_context(
                    conn, self.settings.db_queue
                ):
                    events = await conn.xrange(
                        source_stream, min=event_id, max=event_id
                    )
                    if not events:
                        raise RedisError(
                            f"Событие {event_id} не найдено в {source_stream}"
                        )

                    _, event_data = events[0]

                    # Добавляем метаданные
                    event_data["moved_at"] = datetime.now().isoformat()
                    if additional_data:
                        event_data.update(additional_data)

                    # Записываем в целевой стрим и удаляем из исходного
                    await conn.xadd(dest_stream, event_data, id="*")
                    await conn.xdel(source_stream, event_id)
                    self.logger.debug(
                        f"Событие {event_id} перемещено из {source_stream} в {dest_stream}"
                    )
        except RedisError as exc:
            self.logger.error(
                f"Ошибка перемещения события: {str(exc)}", exc_info=True
            )
            raise

    async def stream_read(
        self,
        stream: str,
        last_id: str = "$",
        count: int = 100,
        block_ms: int = 5000,
        ack: bool = False,
        consumer_group: Tuple[str, str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Читает события из стрима с поддержкой групп потребителей.

        Args:
            stream: Имя стрима для чтения.
            last_id: Идентификатор последнего полученного события.
            count: Максимальное количество событий для возврата.
            block_ms: Время блокировки в миллисекундах.
            ack: Автоматически подтверждать сообщения после чтения.
            consumer_group: Кортеж с именем группы и потребителя.

        Returns:
            List[Dict[str, Any]]: Список событий с метаданными.

        Raises:
            RedisError: Если чтение не удалось.
        """
        try:
            async with self.connection() as conn:
                async with self._switch_db_context(
                    conn, self.settings.db_queue
                ):
                    if consumer_group:
                        group, consumer = consumer_group
                        events = await conn.xreadgroup(
                            groupname=group,
                            consumername=consumer,
                            streams={stream: last_id},
                            count=count,
                            block=block_ms,
                        )
                    else:
                        events = await conn.xread(
                            streams={stream: last_id},
                            count=count,
                            block=block_ms,
                        )

                    result = []
                    for _, stream_events in events:
                        for event_id, event_data in stream_events:
                            entry = {
                                "id": event_id,
                                "stream": stream,
                                "data": event_data,
                            }
                            if ack and consumer_group:
                                await conn.xack(
                                    stream, consumer_group[0], event_id
                                )
                            result.append(entry)

                    return result
        except RedisError as exc:
            self.logger.error(
                f"Ошибка чтения из стрима: {str(exc)}", exc_info=True
            )
            raise

    async def stream_get_stats(
        self, stream: str, num_last_events: int = 5
    ) -> Dict[str, Any]:
        """Получает статистику и последние события стрима.

        Args:
            stream: Имя стрима для анализа.
            num_last_events: Количество последних событий для возврата.

        Returns:
            Dict[str, Any]: Словарь со статистикой стрима.

        Raises:
            RedisError: Если операция не удалась.
        """
        try:
            async with self.connection() as conn:
                async with self._switch_db_context(
                    conn, self.settings.db_queue
                ):
                    return {
                        "length": await conn.xlen(stream),
                        "last_events": await conn.xrevrange(
                            stream, count=num_last_events
                        ),
                        "first_event": await conn.xrange(stream, count=1),
                        "groups": await conn.xinfo_groups(stream),
                    }
        except RedisError as exc:
            self.logger.error(
                f"Ошибка получения статистики стрима: {str(exc)}",
                exc_info=True,
            )
            raise

    async def stream_retry_event(
        self,
        stream: str,
        event_id: str,
        retry_field: str = "retries",
        max_retries: int = settings.redis.max_retries,
        ttl_field: str | None = "expires_at",
        ttl: timedelta | None = None,
    ) -> bool:
        """Повторяет событие с обновленными метаданными.

        Args:
            stream: Имя целевого стрима.
            event_id: Идентификатор события для повторной обработки.
            retry_field: Имя поля для счетчика повторных попыток.
            max_retries: Максимальное количество разрешенных попыток.
            ttl_field: Имя поля для TTL (время жизни).
            ttl: Новое значение TTL.

        Returns:
            bool: True, если повторная попытка успешна, False, если достигнут лимит попыток.

        Raises:
            RedisError: Если операция не удалась.
        """
        from app.utils.utils import utilities

        try:
            async with self.connection() as conn:
                async with self._switch_db_context(
                    conn, self.settings.db_queue
                ):
                    events = await conn.xrange(
                        stream, min=event_id, max=event_id
                    )
                    if not events:
                        return False

                    _, event_data = events[0]

                    event_data = utilities.decode_bytes(data=event_data)

                    current_retries = int(event_data.get(retry_field, 0))

                    if current_retries > max_retries:
                        return False

                    event_data[retry_field] = str(current_retries + 1)

                    if ttl and ttl_field:
                        event_data[ttl_field] = (
                            datetime.now() + ttl
                        ).isoformat()

                    await conn.xadd(stream, event_data, id="*")
                    await conn.xdel(stream, event_id)
                    return True
        except RedisError as exc:
            self.logger.error(
                f"Ошибка повторной обработки события: {str(exc)}",
                exc_info=True,
            )
            raise

    async def list_cache_keys(
        self, pattern: str = "*"
    ) -> Dict[str, List[str]]:
        """Возвращает список ключей кэша, соответствующих шаблону.

        Args:
            pattern: Шаблон для поиска ключей (по умолчанию "*" — все ключи).

        Returns:
            Dict[str, List[str]]: Словарь с ключами кэша.
        """
        keys = []
        try:
            async with self.connection() as conn:
                async for key in conn.scan_iter(match=pattern):
                    keys.append(key.decode())
        except RedisError as exc:
            self.logger.error(
                f"Ошибка при получении ключей кэша: {str(exc)}", exc_info=True
            )
            raise
        return {"keys": keys}

    async def get_cache_value(self, key: str) -> Dict[str, str | None]:
        """Возвращает значение по ключу кэша.

        Args:
            key: Ключ кэша.

        Returns:
            Dict[str, str | None]: Словарь с ключом и его значением.
        """
        try:
            async with self.connection() as conn:
                value = await conn.get(key)
                return {key: value.decode() if value else None}
        except RedisError as exc:
            self.logger.error(
                f"Ошибка при получении значения кэша: {str(exc)}",
                exc_info=True,
            )
            raise

    async def invalidate_cache(self) -> Dict[str, str]:
        """Инвалидирует весь кэш (удаляет все ключи).

        Returns:
            Dict[str, str]: Сообщение о результате операции.
        """
        try:
            async with self.connection() as conn:
                await conn.flushdb()
                return {"status": "Кэш успешно очищен"}
        except RedisError as exc:
            self.logger.error(
                f"Ошибка при инвалидации кэша: {str(exc)}", exc_info=True
            )
            raise


# Singleton-экземпляр для использования в приложении
redis_client = RedisClient(settings=settings.redis)
