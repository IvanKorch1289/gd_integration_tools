"""Unit-тесты ``BaseProtocolAdapter`` (dsl/adapters/base.py).

Покрывают:
* абстрактность ``BaseProtocolAdapter`` (нельзя инстанцировать напрямую);
* сигнатуру abstract-методов (subclass обязан реализовать все 4);
* ``enrich_meta`` устанавливает ``meta.protocol`` и ``meta.protocol_attrs``;
* ``enrich_meta`` корректно мержит множественные kwargs в ``protocol_attrs``;
* ``enrich_meta`` не затирает ранее выставленные protocol_attrs (merge-семантика).

T-P0.1.20 — P0 v9 small worst-файл, цель 80%+ coverage.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.adapters.base import BaseProtocolAdapter
from src.backend.dsl.adapters.types import ProtocolType
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message


class _ConcreteAdapter(BaseProtocolAdapter):
    """Минимальная concrete-реализация для тестов ``BaseProtocolAdapter``."""

    protocol = ProtocolType.rest

    async def create_exchange(self, raw_input: Any) -> Exchange[Any]:
        return Exchange(in_message=Message(body=raw_input))

    async def send_response(
        self, exchange: Exchange[Any], raw_context: Any
    ) -> Any:
        if exchange.out_message is not None:
            return exchange.out_message.body
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class TestAbstractness:
    def test_cannot_instantiate_base_directly(self) -> None:
        """``BaseProtocolAdapter`` — ABC: прямое создание объекта запрещено."""
        with pytest.raises(TypeError):
            BaseProtocolAdapter()  # type: ignore[abstract]

    def test_partial_subclass_still_abstract(self) -> None:
        """Частичная реализация (без одного abstract-метода) тоже ABC."""

        class _Partial(BaseProtocolAdapter):
            protocol = ProtocolType.grpc

            async def create_exchange(self, raw_input: Any) -> Exchange[Any]:
                return Exchange(in_message=Message(body=raw_input))

        # Без send_response/start/stop — всё ещё abstract.
        with pytest.raises(TypeError):
            _Partial()  # type: ignore[abstract]

    def test_full_subclass_can_be_instantiated(self) -> None:
        """Полная реализация всех 4 abstract-методов инстанцируется."""
        adapter = _ConcreteAdapter()
        assert isinstance(adapter, BaseProtocolAdapter)
        assert adapter.protocol == ProtocolType.rest


class TestEnrichMeta:
    def test_enrich_meta_sets_protocol(self) -> None:
        """``enrich_meta`` выставляет ``meta.protocol = self.protocol``."""
        adapter = _ConcreteAdapter()
        exchange: Exchange[Any] = Exchange()

        assert exchange.meta.protocol is None
        adapter.enrich_meta(exchange)
        assert exchange.meta.protocol == ProtocolType.rest

    def test_enrich_meta_sets_attrs(self) -> None:
        """``enrich_meta`` записывает переданные kwargs в ``protocol_attrs``."""
        adapter = _ConcreteAdapter()
        exchange: Exchange[Any] = Exchange()

        adapter.enrich_meta(
            exchange,
            soap_action="GetUser",
            grpc_status="OK",
        )
        assert exchange.meta.protocol_attrs == {
            "soap_action": "GetUser",
            "grpc_status": "OK",
        }

    def test_enrich_meta_empty_kwargs(self) -> None:
        """Без kwargs ``protocol_attrs`` остаётся пустым dict (но не None)."""
        adapter = _ConcreteAdapter()
        exchange: Exchange[Any] = Exchange()

        adapter.enrich_meta(exchange)
        assert exchange.meta.protocol == ProtocolType.rest
        assert exchange.meta.protocol_attrs == {}

    def test_enrich_meta_merges_existing_attrs(self) -> None:
        """Повторный вызов ``enrich_meta`` мержит kwargs в ``protocol_attrs``.

        Поведение контрактное: ранее записанные attrs сохраняются
        (используется ``dict.update``), новые — дописываются.
        """
        adapter = _ConcreteAdapter()
        exchange: Exchange[Any] = Exchange()
        exchange.meta.protocol_attrs = {"existing": "value"}

        adapter.enrich_meta(exchange, new_key="new_value")
        assert exchange.meta.protocol_attrs == {
            "existing": "value",
            "new_key": "new_value",
        }

    def test_enrich_meta_overrides_existing_key(self) -> None:
        """Повторный вызов с тем же ключом — новый kwargs перезаписывает старый."""
        adapter = _ConcreteAdapter()
        exchange: Exchange[Any] = Exchange()
        exchange.meta.protocol_attrs = {"status": "old"}

        adapter.enrich_meta(exchange, status="new")
        assert exchange.meta.protocol_attrs == {"status": "new"}


class TestConcreteAdapterContract:
    """Дымовой контракт: ``_ConcreteAdapter`` корректно реализует API."""

    async def test_create_exchange(self) -> None:
        adapter = _ConcreteAdapter()
        exchange = await adapter.create_exchange({"k": "v"})

        assert isinstance(exchange, Exchange)
        assert exchange.in_message.body == {"k": "v"}
        assert exchange.status == ExchangeStatus.pending

    async def test_send_response_returns_out_body(self) -> None:
        adapter = _ConcreteAdapter()
        exchange: Exchange[Any] = Exchange()
        exchange.set_out(body={"result": 1})

        result = await adapter.send_response(exchange, raw_context=None)
        assert result == {"result": 1}

    async def test_send_response_returns_none_when_no_out(self) -> None:
        adapter = _ConcreteAdapter()
        exchange: Exchange[Any] = Exchange()

        result = await adapter.send_response(exchange, raw_context=None)
        assert result is None

    async def test_start_stop_noop(self) -> None:
        adapter = _ConcreteAdapter()
        # start/stop — async no-op в тестируемом concrete-классе,
        # должны успешно завершаться без побочных эффектов.
        assert await adapter.start() is None
        assert await adapter.stop() is None
