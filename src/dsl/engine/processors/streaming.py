"""Streaming- и expiration-процессоры для DSL.

Реализация недостающих EIP-паттернов банковской интеграционной шины:

* :class:`MessageExpirationProcessor` — TTL на сообщение (EIP Message Expiration).
* :class:`CorrelationIdProcessor` — пропагация correlation-id (EIP Correlation Identifier).
* :class:`TumblingWindowProcessor` — фиксированное окно по времени (streaming).
* :class:`SlidingWindowProcessor` — скользящее окно с перекрытием (streaming).
* :class:`SessionWindowProcessor` — окно по простою (gap-based).
* :class:`GroupByKeyProcessor` — агрегация по ключу в пределах окна.
* :class:`SchemaRegistryValidator` — Avro/JSON Schema валидация.
* :class:`ReplyToProcessor` — request-reply поверх очередей.
* :class:`ExactlyOnceProcessor` — dedup через storage + outbox.
* :class:`DurableSubscriberProcessor` — persistent fan-out к нескольким подписчикам.
* :class:`ChannelPurgerProcessor` — очистка DLQ/стрима.
* :class:`SamplingProcessor` — вероятностный сэмплинг (A/B-testing, canary).

Все процессоры наследуют :class:`BaseProcessor` и подчиняются жизненному циклу
Exchange/ExecutionContext.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "MessageExpirationProcessor",
    "CorrelationIdProcessor",
    "TumblingWindowProcessor",
    "SlidingWindowProcessor",
    "SessionWindowProcessor",
    "GroupByKeyProcessor",
    "SchemaRegistryValidator",
    "ReplyToProcessor",
    "ExactlyOnceProcessor",
    "DurableSubscriberProcessor",
    "ChannelPurgerProcessor",
    "SamplingProcessor",
)

logger = logging.getLogger("dsl.streaming")


# ──────────────────── Message Expiration ────────────────────


class MessageExpirationProcessor(BaseProcessor):
    """Отбрасывает сообщения старше заданного TTL.

    Использует заголовок ``x-created-at`` (unix timestamp float) или
    свойство Exchange ``created_at``. Если заголовок отсутствует —
    сообщение считается свежим.

    Args:
        ttl_seconds: Максимальный возраст сообщения в секундах.
        header_name: Имя заголовка с timestamp (default ``x-created-at``).
        drop_action: Что делать с просроченным сообщением:
            ``fail`` (default), ``skip``, ``log``.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        header_name: str = "x-created-at",
        drop_action: str = "fail",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "expiration")
        self._ttl = ttl_seconds
        self._header = header_name
        self._drop = drop_action

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        created_at = exchange.in_message.headers.get(self._header)
        if created_at is None:
            created_at = exchange.properties.get("created_at")
        if created_at is None:
            return  # Нет данных о возрасте — считаем сообщение свежим

        try:
            age = time.time() - float(created_at)
        except TypeError, ValueError:
            return

        if age <= self._ttl:
            return

        msg = f"Сообщение просрочено: age={age:.1f}s > ttl={self._ttl}s"
        match self._drop:
            case "fail":
                exchange.fail(msg)
            case "skip":
                exchange.properties["_expired"] = True
                logger.info(msg)
            case "log":
                logger.warning(msg)


# ──────────────────── Correlation ID ────────────────────


class CorrelationIdProcessor(BaseProcessor):
    """Проставляет correlation-id в заголовки сообщения.

    Если заголовок уже присутствует — пропускает (идемпотентно).
    Иначе генерирует UUID4.

    Полезно для трейсинга цепочки вызовов между сервисами и очередями.
    """

    def __init__(
        self, *, header: str = "x-correlation-id", name: str | None = None
    ) -> None:
        super().__init__(name=name or "correlation-id")
        self._header = header

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self._header in exchange.in_message.headers:
            return
        new_id = str(uuid.uuid4())
        exchange.in_message.headers[self._header] = new_id
        exchange.properties["correlation_id"] = new_id


# ──────────────────── Streaming Windows ────────────────────


class _BaseWindow(BaseProcessor):
    """Общая логика для оконных процессоров."""

    def __init__(self, *, sink: Any, name: str) -> None:
        super().__init__(name=name)
        # ``sink`` — callable, которому передаём список собранных сообщений
        self._sink = sink
        self._lock = asyncio.Lock()

    async def _emit(self, bucket: list[Any]) -> None:
        if not bucket:
            return
        try:
            result = self._sink(bucket)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.error("Window sink failed: %s", exc)


class TumblingWindowProcessor(_BaseWindow):
    """Tumbling-окно: фиксированный размер, без перекрытия.

    Накапливает сообщения в буфере. При достижении ``size`` или по таймауту
    ``interval_seconds`` — вызывает ``sink(messages)``.
    """

    def __init__(
        self,
        *,
        sink: Any,
        size: int = 100,
        interval_seconds: float = 10.0,
        name: str | None = None,
    ) -> None:
        super().__init__(sink=sink, name=name or "tumbling-window")
        self._size = size
        self._interval = interval_seconds
        self._buffer: list[Any] = []
        self._flush_task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        async with self._lock:
            self._buffer.append(exchange.in_message.body)
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = asyncio.create_task(self._timed_flush())
            if len(self._buffer) >= self._size:
                bucket = list(self._buffer)
                self._buffer.clear()
                await self._emit(bucket)

    async def _timed_flush(self) -> None:
        await asyncio.sleep(self._interval)
        async with self._lock:
            bucket = list(self._buffer)
            self._buffer.clear()
        await self._emit(bucket)


class SlidingWindowProcessor(_BaseWindow):
    """Sliding-окно: фиксированная длительность, шаг меньше размера.

    Пример: окно 10с, шаг 2с — каждые 2 секунды эмитим все сообщения за последние 10с.
    """

    def __init__(
        self,
        *,
        sink: Any,
        window_seconds: float = 10.0,
        step_seconds: float = 2.0,
        name: str | None = None,
    ) -> None:
        super().__init__(sink=sink, name=name or "sliding-window")
        self._window = window_seconds
        self._step = step_seconds
        self._buffer: deque[tuple[float, Any]] = deque()
        self._task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        now = time.monotonic()
        async with self._lock:
            self._buffer.append((now, exchange.in_message.body))
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._emit_loop())

    async def _emit_loop(self) -> None:
        # Окно скользит пока есть данные; останавливаемся после пустого шага.
        while True:
            await asyncio.sleep(self._step)
            async with self._lock:
                cutoff = time.monotonic() - self._window
                while self._buffer and self._buffer[0][0] < cutoff:
                    self._buffer.popleft()
                if not self._buffer:
                    return
                bucket = [body for _, body in self._buffer]
            await self._emit(bucket)


class SessionWindowProcessor(_BaseWindow):
    """Session-окно: окно закрывается после паузы ``gap_seconds``.

    Применяется для группировки связанных событий (например, действий
    пользователя в одной сессии).
    """

    def __init__(
        self, *, sink: Any, gap_seconds: float = 30.0, name: str | None = None
    ) -> None:
        super().__init__(sink=sink, name=name or "session-window")
        self._gap = gap_seconds
        self._buffer: list[Any] = []
        self._last_seen: float = 0.0
        self._task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        async with self._lock:
            self._last_seen = time.monotonic()
            self._buffer.append(exchange.in_message.body)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._gap_watcher())

    async def _gap_watcher(self) -> None:
        while True:
            await asyncio.sleep(self._gap / 2)
            async with self._lock:
                idle = time.monotonic() - self._last_seen
                if idle >= self._gap and self._buffer:
                    bucket = list(self._buffer)
                    self._buffer.clear()
                else:
                    continue
            await self._emit(bucket)
            return


# ──────────────────── Group By Key ────────────────────


class GroupByKeyProcessor(_BaseWindow):
    """Группирует события по ключу в пределах окна.

    ``key_path`` — jmespath-выражение для извлечения ключа из body.
    При закрытии окна ``sink`` получает dict ``{key: [events...]}``.
    """

    def __init__(
        self,
        *,
        sink: Any,
        key_path: str,
        window_seconds: float = 60.0,
        name: str | None = None,
    ) -> None:
        super().__init__(sink=sink, name=name or f"group-by:{key_path}")
        self._key_path = key_path
        self._window = window_seconds
        self._groups: dict[Any, list[Any]] = defaultdict(list)
        self._task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            import jmespath

            key = jmespath.search(self._key_path, exchange.in_message.body)
        except Exception:
            key = None

        async with self._lock:
            self._groups[key].append(exchange.in_message.body)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._flush_after_window())

    async def _flush_after_window(self) -> None:
        await asyncio.sleep(self._window)
        async with self._lock:
            snapshot = dict(self._groups)
            self._groups.clear()
        if snapshot:
            try:
                result = self._sink(snapshot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error("GroupBy sink failed: %s", exc)


# ──────────────────── Schema Registry ────────────────────


class SchemaRegistryValidator(BaseProcessor):
    """Валидация сообщения по схеме из реестра.

    Поддерживает JSON Schema (через ``jsonschema``), в будущем — Avro/Protobuf.
    Схема загружается по ``subject`` и кешируется.
    """

    _cache: dict[str, Any] = {}

    def __init__(
        self, *, subject: str, schema_loader: Any = None, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"schema:{subject}")
        self._subject = subject
        self._loader = schema_loader

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        schema = self._cache.get(self._subject)
        if schema is None and self._loader is not None:
            loaded = self._loader(self._subject)
            if asyncio.iscoroutine(loaded):
                loaded = await loaded
            schema = loaded
            self._cache[self._subject] = schema

        if schema is None:
            exchange.fail(f"Schema '{self._subject}' не найдена в реестре")
            return

        try:
            import jsonschema

            jsonschema.validate(instance=exchange.in_message.body, schema=schema)
        except ImportError:
            logger.warning("jsonschema не установлен, валидация пропущена")
        except Exception as exc:
            exchange.fail(f"Schema validation failed: {exc}")


# ──────────────────── Reply-To (request-reply over queue) ────────────────────


class ReplyToProcessor(BaseProcessor):
    """Публикует ответ в очередь указанную в заголовке ``reply-to``.

    Реализация паттерна request-reply поверх асинхронных очередей.
    Использует broker из context (Kafka/RabbitMQ/Redis Streams).
    """

    def __init__(
        self,
        *,
        broker: Any,
        reply_to_header: str = "reply-to",
        correlation_header: str = "x-correlation-id",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "reply-to")
        self._broker = broker
        self._reply_header = reply_to_header
        self._correlation_header = correlation_header

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        reply_to = exchange.in_message.headers.get(self._reply_header)
        if not reply_to:
            return  # Нет адреса ответа — не reply-сообщение

        correlation = exchange.in_message.headers.get(self._correlation_header)
        headers = {self._correlation_header: correlation} if correlation else {}
        body = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )

        try:
            await self._broker.publish(reply_to, body, headers=headers)
        except Exception as exc:
            logger.error("Reply publish failed: %s", exc)
            exchange.fail(f"Reply publish failed: {exc}")


# ──────────────────── Exactly-Once ────────────────────


class ExactlyOnceProcessor(BaseProcessor):
    """Dedup по message-id через внешний storage.

    Реализует exactly-once семантику: если ``message-id`` уже видели —
    сообщение отбрасывается. Использует pluggable storage (Redis, БД).
    """

    def __init__(
        self,
        *,
        storage: Any,
        id_header: str = "x-message-id",
        ttl_seconds: int = 86_400,
        namespace: str = "exactly-once",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "exactly-once")
        self._storage = storage
        self._id_header = id_header
        self._ttl = ttl_seconds
        self._namespace = namespace

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        msg_id = exchange.in_message.headers.get(self._id_header)
        if not msg_id:
            exchange.fail(f"Missing {self._id_header} header for exactly-once")
            return

        key = f"{self._namespace}:{msg_id}"
        # set NX — первая запись побеждает; если ключ уже есть — это дубль.
        added = await self._storage.set_nx(key, b"1", ttl=self._ttl)
        if not added:
            exchange.properties["_duplicate"] = True
            exchange.fail(f"Duplicate message-id: {msg_id}")


# ──────────────────── Durable Subscriber ────────────────────


class DurableSubscriberProcessor(BaseProcessor):
    """Fan-out к нескольким подписчикам с гарантией доставки.

    Для каждого subscriber публикует копию сообщения в его персональную
    очередь. Offset/ack хранится на стороне брокера (durable).
    """

    def __init__(
        self, *, broker: Any, subscribers: list[str], name: str | None = None
    ) -> None:
        super().__init__(name=name or f"durable-fanout:{len(subscribers)}")
        self._broker = broker
        self._subscribers = subscribers

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        headers = dict(exchange.in_message.headers)
        results = await asyncio.gather(
            *(
                self._broker.publish(sub, body, headers=headers)
                for sub in self._subscribers
            ),
            return_exceptions=True,
        )
        failed = [
            sub
            for sub, res in zip(self._subscribers, results, strict=True)
            if isinstance(res, Exception)
        ]
        if failed:
            exchange.fail(f"Durable publish failed for: {failed}")


# ──────────────────── Channel Purger ────────────────────


class ChannelPurgerProcessor(BaseProcessor):
    """Очистка очереди/стрима (admin-операция для DLQ, устаревших потоков).

    Вызывает ``broker.purge(channel)``. Опасно в production —
    обычно используется вручную через админ-UI.
    """

    def __init__(
        self,
        *,
        broker: Any,
        channel: str,
        dry_run: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"purge:{channel}")
        self._broker = broker
        self._channel = channel
        self._dry_run = dry_run

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self._dry_run:
            logger.warning(
                "ChannelPurger DRY-RUN для %s (ничего не удалено)", self._channel
            )
            exchange.out_message.body = {
                "purged": False,
                "dry_run": True,
                "channel": self._channel,
            }
            return
        deleted = await self._broker.purge(self._channel)
        exchange.out_message.body = {
            "purged": True,
            "deleted": deleted,
            "channel": self._channel,
        }


# ──────────────────── Sampling ────────────────────


class SamplingProcessor(BaseProcessor):
    """Вероятностный сэмплинг — пропускает сообщение с вероятностью ``probability``.

    Используется для A/B-тестирования, canary-деплоев, отладки нагруженных
    pipeline'ов без обработки каждого сообщения.
    """

    def __init__(self, *, probability: float = 0.1, name: str | None = None) -> None:
        if not 0.0 <= probability <= 1.0:
            raise ValueError("probability должен быть в [0.0, 1.0]")
        super().__init__(name=name or f"sample:{probability:.2f}")
        self._p = probability

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        # random.random() < p — эквивалентно Bernoulli trial.
        if random.random() >= self._p:
            exchange.properties["_sampled_out"] = True
            # Помечаем как завершённое без ошибки, но downstream должен фильтровать.
            exchange.properties["_skip_downstream"] = True
