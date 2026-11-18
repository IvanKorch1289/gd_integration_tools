"""Базовый контейнер сообщений интеграционной шины.

Модели перенесены в ``core``, чтобы infrastructure/workflow не зависел от
DSL-реализации. DSL сохраняет совместимый re-export в
``src.backend.dsl.engine.exchange``.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from src.backend.core.logging import get_logger
from src.backend.core.types.data_kind import DataKind

__all__ = ("Exchange", "ExchangeMeta", "ExchangeStatus", "Message")

T = TypeVar("T")

_logger = get_logger(__name__)


def _make_correlation_id() -> str:
    """Создать correlation ID с propagation from ASGI context.

    Tries asgi_correlation_id.context.correlation_id first (set by
    CorrelationIdMiddleware in entrypoints/middlewares/correlation.py).
    Fallback to uuid4 если ASGI context недоступен (e.g., background tasks,
    CLI scripts, tests).
    """
    try:
        from asgi_correlation_id.context import correlation_id as asgi_cid

        asgi_value = asgi_cid.get("")
        if asgi_value:
            return asgi_value
    except ImportError, LookupError, AttributeError:
        # No asgi_correlation_id context (offline/test) — fallback to UUIDv4
        pass
    return str(uuid.uuid4())


class ExchangeStatus(StrEnum):
    """Статус выполнения Exchange внутри маршрута."""

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Message[T](BaseModel):
    """Универсальное сообщение маршрута.

    Attributes:
        headers: Транспортно-агностичные заголовки.
        body: Полезная нагрузка.
        data_kind: Форма payload'а — ``SINGLE`` (default), ``BATCH`` или
            ``STREAM`` (W14.2). Процессоры, оптимизированные под batch/stream,
            читают это поле в ``process()`` для выбора оптимизированного пути.
        watermark: Wall-clock секунды (Unix epoch); граница "не позже"
            для оконных процессоров (W14.3). ``None`` = watermark не
            эмитился источником.

    """

    headers: dict[str, Any] = Field(default_factory=dict)
    body: T | None = None
    data_kind: DataKind = Field(default=DataKind.SINGLE)
    watermark: float | None = Field(default=None)

    def get_header(self, key: str, default: Any = None) -> Any:
        """Вернуть значение заголовка.

        Args:
            key: Имя заголовка.
            default: Значение по умолчанию.

        Returns:
            Any: Значение заголовка или default.

        """
        return self.headers.get(key, default)

    def set_header(self, key: str, value: Any) -> None:
        """Установить значение заголовка.

        Args:
            key: Имя заголовка.
            value: Новое значение.

        """
        self.headers[key] = value

    def set_body(self, value: T) -> None:
        """Установить тело сообщения."""
        self.body = value


class ExchangeMeta(BaseModel):
    """Служебные метаданные Exchange.

    Attributes:
        exchange_id: Уникальный идентификатор конкретного обмена.
        route_id: Идентификатор маршрута.
        correlation_id: Идентификатор цепочки вызовов.
        created_at: Время создания Exchange.
        source: Имя входного источника (http, grpc, redis, rabbit и т.д.).
        tenant_id: Идентификатор тенанта (K-ARCH-4, S17). Устанавливается
            ExecutionEngine для pipeline'ов с ``tenant_aware=True`` из
            RequestContext или TenantContext.
        principal: Идентификатор исполнителя (ADR-0366). Пробрасывается в
            capability-гейт для аудита; **никогда** не используется как
            namespace доступа (риск ADR-0361).

    """

    exchange_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    route_id: str | None = None
    correlation_id: str = Field(
        default_factory=lambda: _make_correlation_id(),
        description=(
            "S92 M5-#8: идентификатор цепочки вызовов. Default factory — "
            "asgi_correlation_id context (если доступен через "
            "ASGI middleware) ИЛИ fallback UUIDv4. Обеспечивает propagation "
            "HTTP correlation_id → Exchange."
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str | None = None
    protocol: str | None = None
    protocol_attrs: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str | None = None
    principal: str | None = None


class Exchange[T](BaseModel):
    """Контейнер, который движется по маршруту.

    Аналог Camel Exchange:
    - `in_message` — входные данные;
    - `out_message` — результат обработки;
    - `properties` — внутренний runtime-контекст маршрута;
    - `meta` — служебные метаданные;
    - `status/error` — текущее состояние выполнения.
    """

    meta: ExchangeMeta = Field(default_factory=ExchangeMeta)
    in_message: Message[T] = Field(default_factory=Message)
    out_message: Message[Any] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    status: ExchangeStatus = ExchangeStatus.pending
    error: str | None = None

    def get_property(self, key: str, default: Any = None) -> Any:
        """Вернуть runtime-свойство маршрута.

        Args:
            key: Ключ свойства.
            default: Значение по умолчанию.

        Returns:
            Any: Значение свойства или default.

        """
        return self.properties.get(key, default)

    def set_property(self, key: str, value: Any) -> None:
        """Установить runtime-свойство маршрута.

        Args:
            key: Ключ свойства.
            value: Новое значение.

        """
        self.properties[key] = value

    def set_out(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        """Установить выходное сообщение.

        Args:
            body: Результирующее тело.
            headers: Результирующие заголовки.

        """
        self.out_message = Message(body=body, headers=headers or {})

    def complete(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        """Завершить Exchange успешно.

        Args:
            body: Результирующее тело.
            headers: Результирующие заголовки.

        """
        self.set_out(body=body, headers=headers)
        self.status = ExchangeStatus.completed
        self.error = None

    def fail(self, reason: str) -> None:
        """Завершить Exchange ошибкой.

        Args:
            reason: Текст ошибки.

        """
        self.status = ExchangeStatus.failed
        self.error = reason

    def stop(self) -> None:
        """Прервать дальнейшую обработку маршрута."""
        self.set_property("_stopped", True)

    @property
    def stopped(self) -> bool:
        """Проверить, была ли остановлена обработка."""
        return self.properties.get("_stopped", False)

    def add_finalizer(self, fn: Callable[[], Awaitable[None] | None]) -> None:
        """Зарегистрировать cleanup-колбэк для выполнения в конце route.

        Finalizers (async или sync) выполняются best-effort через
        :meth:`run_finalizers` — обычно execution engine после прогона всех
        processors. Используется для освобождения ресурсов (напр. browser
        context из :class:`~src.backend.services.rpa.browser_pool.PlaywrightBrowserPool`),
        которые переживают один processor.

        Args:
            fn: Колбэк без аргументов. Может быть coroutine-function; если
                возвращает awaitable — он ожидается.

        """
        self.properties.setdefault("_finalizers", []).append(fn)

    async def run_finalizers(self) -> None:
        """Выполнить все зарегистрированные finalizers в обратном порядке (LIFO).

        Каждый finalizer изолирован: исключение в одном не блокирует остальные.
        Хранилище ``properties['_finalizers']`` очищается после выполнения
        (idempotent — повторный вызов no-op).
        """
        finalizers: list[Callable[[], Awaitable[None] | None]] = self.properties.pop(
            "_finalizers", []
        )
        for fn in reversed(finalizers):
            try:
                result = fn()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                _logger.debug("finalizer %r failed: %s", fn, exc)

    def set_error(self, reason: str) -> None:
        """Установить ошибку без изменения статуса."""
        self.error = reason

    def clone(self, *, body: Any = None) -> Exchange[Any]:
        """Создать копию Exchange для параллельной обработки.

        Копирует in_message (с опциональной заменой body),
        headers, properties и metadata. Новый exchange начинает
        со статуса processing.

        ``_finalizers`` НЕ копируются: родитель владеет ресурсом и
        освобождает его своим finalizer (напр. browser context); клон,
        читающий ``properties['rpa.page']``, не должен дублировать cleanup.

        ``tenant_id`` и ``principal`` копируются **обязательно**: capability-гейт
        процессора берёт tenant из ``exchange.meta.tenant_id`` (без него —
        платформенный scope ``_system``), а tenant-aware процессоры агентов
        (``ai.memory.*``, ``ai.tool.*``) берут его же — без копирования клон
        работал бы в чужом namespace (``tenant_id or "unknown"``).
        """
        cloned = Exchange(
            in_message=Message(
                body=body if body is not None else self.in_message.body,
                headers=dict(self.in_message.headers),
                data_kind=self.in_message.data_kind,
                watermark=self.in_message.watermark,
            )
        )
        cloned.meta.route_id = self.meta.route_id
        cloned.meta.correlation_id = self.meta.correlation_id
        cloned.meta.tenant_id = self.meta.tenant_id
        cloned.meta.principal = self.meta.principal
        cloned.meta.source = self.meta.source
        cloned.meta.protocol = self.meta.protocol
        cloned.meta.protocol_attrs = dict(self.meta.protocol_attrs)
        cloned.properties = {
            k: v for k, v in self.properties.items() if k != "_finalizers"
        }
        cloned.status = ExchangeStatus.processing
        return cloned
