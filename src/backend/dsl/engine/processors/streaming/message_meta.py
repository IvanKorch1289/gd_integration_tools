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
import uuid
from typing import Any, ClassVar

from src.backend.core.clock import RealClock
from src.backend.core.interfaces.clock import Clock
from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

logger = get_logger("dsl.streaming")


# ──────────────────── Message Expiration ────────────────────


# ── message-level metadata (expiration, correlation ID, schema validation) ──


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
        """Проверяет возраст сообщения и отбрасывает просроченные."""
        created_at = exchange.in_message.headers.get(self._header)
        if created_at is None:
            created_at = exchange.properties.get("created_at")
        if created_at is None:
            return  # Нет данных о возрасте — считаем сообщение свежим

        try:
            age = self._clock.time() - float(created_at)
        except (TypeError, ValueError):
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


class SchemaRegistryValidator(BaseProcessor):
    """Валидация сообщения по схеме из реестра.

    Поддерживает JSON Schema (через ``jsonschema``), в будущем — Avro/Protobuf.
    Схема загружается по ``subject`` и кешируется.
    """

    _cache: ClassVar[dict[str, Any]] = {}

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
