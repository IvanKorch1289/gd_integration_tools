"""Wave 6.2 — DSL-процессор CDC Capture: читает изменения из внешней БД.

Использует :class:`CDCClient` (через ``get_cdc_client``) для подписки на
изменения таблиц. CDC-события стандартизованы::

    {
        "operation": "INSERT|UPDATE|DELETE|UPSERT",
        "table": "orders",
        "timestamp": "2026-04-19T12:00:00",
        "old": {...},  # для UPDATE/DELETE (если доступно)
        "new": {...},  # для INSERT/UPDATE
        "profile": "oracle_prod",
    }

Контракт DSL::

    .cdc_capture(
        profile="oracle_prod",
        tables=["orders", "customers"],
        strategy="polling",
        result_property="cdc_events",
    )
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

try:
    # S67 M2-#11 batch 2: DI provider вместо inline infrastructure import.
    # get_cdc_client_provider() сам handle'ит ImportError (resolve_module lazy).
    from src.backend.core.di.providers.db import get_cdc_client_provider
except ImportError:
    get_cdc_client_provider = None  # type: ignore[assignment]

__all__ = ("CDCCaptureProcessor",)


_ALLOWED_STRATEGIES = frozenset({"polling", "listen_notify", "logminer", "kafka"})

#: Максимум CDC-событий, удерживаемых процессором (bounded-memory).
_MAX_EVENTS = 1000


class CDCCaptureProcessor(BaseProcessor):
    """Читает изменения из внешней БД через CDC и кладёт события в result_property.

    Args:
        profile: Имя профиля внешней БД (см. ``settings.external_databases.profiles``).
        tables: Список таблиц для отслеживания изменений.
        strategy: Стратегия обнаружения — ``"polling"`` (любая БД),
            ``"listen_notify"`` (PostgreSQL LISTEN/NOTIFY),
            ``"logminer"`` (Oracle LogMiner),
            ``"kafka"`` (Debezium через Kafka topic; S62 W2).
        result_property: Ключ ``Exchange.properties``, в который записать
            список CDC-событий. Также пишется в ``out_message.body``.
        interval: Интервал polling в секундах (default 5.0).
        timestamp_column: Столбец для polling-стратегии (default ``"updated_at"``).
        batch_size: Макс. событий за итерацию (default 100).
        channel: Имя PostgreSQL-канала для listen_notify (default ``cdc_<table>``).
        include_schema: Включать схему таблицы в события (default ``True``).

    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        profile: str,
        tables: list[str],
        *,
        strategy: str = "polling",
        result_property: str = "cdc_events",
        interval: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        channel: str | None = None,
        include_schema: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"cdc_capture:{profile}:{strategy}")
        if strategy not in _ALLOWED_STRATEGIES:
            raise ValueError(
                f"strategy must be one of {sorted(_ALLOWED_STRATEGIES)}, "
                f"got: {strategy!r}"
            )
        if not tables:
            raise ValueError("tables cannot be empty")
        self._profile = profile
        self._tables = tables
        self._strategy = strategy
        self._result_property = result_property
        self._interval = interval
        self._timestamp_column = timestamp_column
        self._batch_size = batch_size
        self._channel = channel
        self._include_schema = include_schema
        self._subscription_id: str | None = None
        # ADR-0384: события CDC-клиента приходят асинхронно (callback) —
        # процессор накапливает их и отдаёт в result_property.
        self._events: list[dict[str, Any]] = []
        self._exchange: Exchange[Any] | None = None

    async def _on_event(self, event: dict[str, Any]) -> None:
        """Callback CDC-клиента: событие попадает в ``result_property``.

        Args:
            event: Событие CDC (dict с ключами operation/table/timestamp/...).

        """
        self._events.append(event)
        if len(self._events) > _MAX_EVENTS:
            del self._events[: len(self._events) - _MAX_EVENTS]
        exchange = self._exchange
        if exchange is not None:
            exchange.set_property(self._result_property, self._result_payload())
            exchange.in_message.body = list(self._events)

    def _result_payload(self) -> dict[str, Any]:
        """Собрать payload результата подписки + накопленных событий."""
        return {
            "subscription_id": self._subscription_id,
            "profile": self._profile,
            "tables": list(self._tables),
            "strategy": self._strategy,
            "status": "cdc_capture_active",
            "events": list(self._events),
        }

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Подписывается на CDC и записывает события в result_property."""
        if get_cdc_client_provider is None:
            raise ImportError("cdc client not available")

        client = get_cdc_client_provider()
        subscription_id = self._subscription_id

        if subscription_id is None:
            subscription_id = await client.subscribe(
                profile=self._profile,
                tables=self._tables,
                strategy=self._strategy,
                interval=self._interval,
                timestamp_column=self._timestamp_column,
                batch_size=self._batch_size,
                channel=self._channel,
                # ADR-0384: callback обязателен — иначе события CDC
                # дропались на стороне клиента и до result_property
                # не доходили.
                callback=self._on_event,
                target_action=None,
            )
            self._subscription_id = subscription_id

        self._exchange = exchange
        exchange.set_property("cdc_subscription_id", subscription_id)
        exchange.set_property(self._result_property, self._result_payload())
        exchange.set_out(
            body=self._result_payload(),
            headers=dict(exchange.in_message.headers),
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Возвращает round-trip DSL-спецификацию ``{"cdc_capture": {...}}``."""
        spec: dict[str, Any] = {
            "profile": self._profile,
            "tables": self._tables,
            "strategy": self._strategy,
        }
        if self._result_property != "cdc_events":
            spec["result_property"] = self._result_property
        if self._interval != 5.0:
            spec["interval"] = self._interval
        if self._timestamp_column != "updated_at":
            spec["timestamp_column"] = self._timestamp_column
        if self._batch_size != 100:
            spec["batch_size"] = self._batch_size
        if self._channel is not None:
            spec["channel"] = self._channel
        if self._include_schema is not True:
            spec["include_schema"] = self._include_schema
        return {"cdc_capture": spec}
