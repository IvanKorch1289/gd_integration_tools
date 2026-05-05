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
import uuid
from collections import defaultdict, deque
from typing import Any

from src.backend.core.clock import RealClock
from src.backend.core.interfaces.clock import Clock
from src.backend.core.interfaces.watermark_store import WatermarkStore
from src.backend.core.types.watermark import LatePolicy, WatermarkState
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.late_event_policy import apply_late_policy
from src.backend.dsl.engine.processors.base import BaseProcessor

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
        clock: Clock | None = None,
    ) -> None:
        super().__init__(name=name or "expiration")
        self._ttl = ttl_seconds
        self._header = header_name
        self._drop = drop_action
        self._clock: Clock = clock or RealClock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        created_at = exchange.in_message.headers.get(self._header)
        if created_at is None:
            created_at = exchange.properties.get("created_at")
        if created_at is None:
            return  # Нет данных о возрасте — считаем сообщение свежим

        try:
            age = self._clock.time() - float(created_at)
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
    """Общая логика для оконных процессоров.

    Args:
        sink: Callable, получающий список накопленных сообщений.
        name: Имя процессора (для логирования и метрик).
        clock: Источник времени; default ``RealClock`` (production).
            В тестах подменяется на ``FakeClock``.
        allowed_lateness_seconds: Дополнительный допуск для late events
            (W14.3). 0 = строгий watermark.
        late_policy: Что делать с late events: ``DROP`` (default),
            ``SIDE_OUTPUT``, ``REPROCESS``.
        watermark_store: Опциональный персистентный backend (W14.5).
            При наличии вместе с ``route_id`` watermark переживает рестарт.
        route_id: Идентификатор DSL-маршрута; обязателен совместно с
            ``watermark_store`` для уникальности ключа в store.
        persist_min_interval: Минимальный интервал между сохранениями в
            store (секунды wall-clock). Дебаунс защищает горячий путь.
    """

    def __init__(
        self,
        *,
        sink: Any,
        name: str,
        clock: Clock | None = None,
        allowed_lateness_seconds: float = 0.0,
        late_policy: LatePolicy = LatePolicy.DROP,
        watermark_store: WatermarkStore | None = None,
        route_id: str | None = None,
        persist_min_interval: float = 1.0,
    ) -> None:
        super().__init__(name=name)
        # ``sink`` — callable, которому передаём список собранных сообщений
        self._sink = sink
        self._lock = asyncio.Lock()
        self._clock: Clock = clock or RealClock()
        self._allowed_lateness = allowed_lateness_seconds
        self._late_policy = late_policy
        self._watermark = WatermarkState()
        self._store = watermark_store
        self._route_id = route_id
        self._persist_min_interval = persist_min_interval
        self._last_persisted_at: float = 0.0
        self._loaded_from_store: bool = False

    @property
    def watermark_state(self) -> WatermarkState:
        """Снимок текущего watermark (для тестов и метрик)."""
        return self._watermark

    async def _ensure_loaded(self) -> None:
        """Lazy-загрузка watermark из store при первом обращении.

        Вызов идемпотентен. Если store/route_id не заданы — no-op.
        """
        if self._loaded_from_store or self._store is None or self._route_id is None:
            return
        loaded = await self._store.load(self._route_id, self.name)
        if loaded is not None and loaded.current > self._watermark.current:
            self._watermark = loaded
        self._loaded_from_store = True

    async def _maybe_persist(self) -> None:
        """Сохранить watermark в store с дебаунсом.

        Persist выполняется не чаще, чем раз в ``persist_min_interval``
        секунд wall-clock. ``-inf`` (advance ещё не происходил) пропускаем
        — состояние не несёт информации.
        """
        if self._store is None or self._route_id is None:
            return
        if self._watermark.current == float("-inf"):
            return
        now = self._clock.time()
        if (now - self._last_persisted_at) < self._persist_min_interval:
            return
        try:
            await self._store.save(self._route_id, self.name, self._watermark)
            self._last_persisted_at = now
        except Exception as exc:
            logger.error("Watermark persist failed: %s", exc)

    async def _is_late_and_handle(self, exchange: Exchange[Any]) -> bool:
        """Проверить exchange на late event и применить политику.

        Returns:
            ``True`` если событие отброшено (engine должен прекратить
            обработку), ``False`` если можно класть в bucket.
        """
        await self._ensure_loaded()
        msg_watermark = exchange.in_message.watermark
        if msg_watermark is None:
            return False
        # Продвигаем watermark процессора до значения из сообщения.
        advanced = self._watermark.advance(msg_watermark, now=self._clock.time())
        if advanced:
            await self._maybe_persist()
        # event_time = заголовок x-event-time или wall-clock.
        event_time_raw = exchange.in_message.headers.get("x-event-time")
        try:
            event_time = float(event_time_raw) if event_time_raw is not None else None
        except TypeError, ValueError:
            event_time = None
        if event_time is None:
            return False
        if not self._watermark.is_late(
            event_time, allowed_lateness=self._allowed_lateness
        ):
            return False
        keep = await apply_late_policy(
            exchange, state=self._watermark, policy=self._late_policy
        )
        # Late-counter изменился — пробуем персистнуть (тоже под дебаунсом).
        await self._maybe_persist()
        return not keep

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
        clock: Clock | None = None,
        allowed_lateness_seconds: float = 0.0,
        late_policy: LatePolicy = LatePolicy.DROP,
        watermark_store: WatermarkStore | None = None,
        route_id: str | None = None,
        persist_min_interval: float = 1.0,
    ) -> None:
        super().__init__(
            sink=sink,
            name=name or "tumbling-window",
            clock=clock,
            allowed_lateness_seconds=allowed_lateness_seconds,
            late_policy=late_policy,
            watermark_store=watermark_store,
            route_id=route_id,
            persist_min_interval=persist_min_interval,
        )
        self._size = size
        self._interval = interval_seconds
        self._buffer: list[Any] = []
        self._flush_task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        # Late event — engine применяет политику и прекращает обработку.
        if await self._is_late_and_handle(exchange):
            return
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

    Late events отбрасываются согласно ``late_policy`` (по аналогии с
    Tumbling). Watermark берётся из ``message.watermark``, event_time —
    из заголовка ``x-event-time``.
    """

    def __init__(
        self,
        *,
        sink: Any,
        window_seconds: float = 10.0,
        step_seconds: float = 2.0,
        name: str | None = None,
        clock: Clock | None = None,
        allowed_lateness_seconds: float = 0.0,
        late_policy: LatePolicy = LatePolicy.DROP,
        watermark_store: WatermarkStore | None = None,
        route_id: str | None = None,
        persist_min_interval: float = 1.0,
    ) -> None:
        super().__init__(
            sink=sink,
            name=name or "sliding-window",
            clock=clock,
            allowed_lateness_seconds=allowed_lateness_seconds,
            late_policy=late_policy,
            watermark_store=watermark_store,
            route_id=route_id,
            persist_min_interval=persist_min_interval,
        )
        self._window = window_seconds
        self._step = step_seconds
        self._buffer: deque[tuple[float, Any]] = deque()
        self._task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if await self._is_late_and_handle(exchange):
            return
        now = self._clock.monotonic()
        async with self._lock:
            self._buffer.append((now, exchange.in_message.body))
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._emit_loop())

    async def _emit_loop(self) -> None:
        # Окно скользит пока есть данные; останавливаемся после пустого шага.
        while True:
            await asyncio.sleep(self._step)
            async with self._lock:
                cutoff = self._clock.monotonic() - self._window
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

    Late events отбрасываются согласно ``late_policy``: событие, чей
    ``event_time`` уже отстал от watermark, не попадает в текущую сессию.
    """

    def __init__(
        self,
        *,
        sink: Any,
        gap_seconds: float = 30.0,
        name: str | None = None,
        clock: Clock | None = None,
        allowed_lateness_seconds: float = 0.0,
        late_policy: LatePolicy = LatePolicy.DROP,
        watermark_store: WatermarkStore | None = None,
        route_id: str | None = None,
        persist_min_interval: float = 1.0,
    ) -> None:
        super().__init__(
            sink=sink,
            name=name or "session-window",
            clock=clock,
            allowed_lateness_seconds=allowed_lateness_seconds,
            late_policy=late_policy,
            watermark_store=watermark_store,
            route_id=route_id,
            persist_min_interval=persist_min_interval,
        )
        self._gap = gap_seconds
        self._buffer: list[Any] = []
        self._last_seen: float = 0.0
        self._task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if await self._is_late_and_handle(exchange):
            return
        async with self._lock:
            self._last_seen = self._clock.monotonic()
            self._buffer.append(exchange.in_message.body)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._gap_watcher())

    async def _gap_watcher(self) -> None:
        while True:
            await asyncio.sleep(self._gap / 2)
            async with self._lock:
                idle = self._clock.monotonic() - self._last_seen
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
        clock: Clock | None = None,
    ) -> None:
        super().__init__(sink=sink, name=name or f"group-by:{key_path}", clock=clock)
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
        # random.random() < p — эквивалентно Bernoulli trial (sampling, не крипто).
        if random.random() >= self._p:  # noqa: S311
            exchange.properties["_sampled_out"] = True
            # Помечаем как завершённое без ошибки, но downstream должен фильтровать.
            exchange.properties["_skip_downstream"] = True
