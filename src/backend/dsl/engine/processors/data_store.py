"""DataStore processors — in-memory key-value в рамках Exchange."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("DataStoreDeleteProcessor", "DataStoreGetProcessor", "DataStoreSetProcessor")

_DATA_STORE_KEY = "_data_store"


class DataStoreSetProcessor(BaseProcessor):
    """Сохраняет значение в in-memory dict внутри Exchange.properties."""

    def __init__(self, *, key: str, value: Any, name: str | None = None) -> None:
        super().__init__(name=name or f"data_store_set({key})")
        self._key = key
        self._value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        store: dict[str, Any] = exchange.properties.setdefault(_DATA_STORE_KEY, {})
        store[self._key] = self._value
        exchange.set_out(
            body=exchange.in_message.body, headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {"data_store_set": {"key": self._key, "value": self._value}}


class DataStoreGetProcessor(BaseProcessor):
    """Читает значение из in-memory dict внутри Exchange.properties."""

    def __init__(
        self,
        *,
        key: str,
        default: Any = None,
        result_property: str = "data_store_value",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"data_store_get({key})")
        self._key = key
        self._default = default
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        store: dict[str, Any] = exchange.properties.get(_DATA_STORE_KEY, {})
        result = store.get(self._key, self._default)
        exchange.set_property(self._result_property, result)
        exchange.set_out(
            body=exchange.in_message.body, headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "data_store_get": {
                "key": self._key,
                "default": self._default,
                "result_property": self._result_property,
            }
        }


class DataStoreDeleteProcessor(BaseProcessor):
    """Удаляет ключ из in-memory dict внутри Exchange.properties."""

    def __init__(self, *, key: str, name: str | None = None) -> None:
        super().__init__(name=name or f"data_store_delete({key})")
        self._key = key

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        store: dict[str, Any] = exchange.properties.get(_DATA_STORE_KEY, {})
        store.pop(self._key, None)
        exchange.set_out(
            body=exchange.in_message.body, headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {"data_store_delete": {"key": self._key}}
