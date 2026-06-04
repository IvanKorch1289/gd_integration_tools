"""Unit-тесты ``SoapAdapter`` (dsl/adapters/soap.py).

Покрывают:
* атрибут ``protocol`` равен ``ProtocolType.soap``;
* ``create_exchange`` парсит ``operation``/``payload``/``headers``;
* ``create_exchange`` работает с пустым/частичным raw_input (defaults);
* ``create_exchange`` обогащает ``meta`` (protocol, protocol_attrs);
* ``send_response`` возвращает ``out_message.body`` либо ``None``;
* ``start``/``stop`` — async no-op (stateless).

T-P0.1.20 — P0 v9 small worst-файл, цель 80%+ coverage.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

from src.backend.dsl.adapters.base import BaseProtocolAdapter
from src.backend.dsl.adapters.soap import SoapAdapter
from src.backend.dsl.adapters.types import ProtocolType
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus


class TestProtocolAttribute:
    def test_protocol_is_soap(self) -> None:
        """``SoapAdapter.protocol`` == ``ProtocolType.soap``."""
        assert SoapAdapter.protocol == ProtocolType.soap

    def test_soap_adapter_inherits_base(self) -> None:
        """``SoapAdapter`` — подкласс ``BaseProtocolAdapter``."""
        assert issubclass(SoapAdapter, BaseProtocolAdapter)


class TestCreateExchange:
    async def test_full_input(self) -> None:
        """Полный вход: operation, payload, headers — корректный Exchange."""
        adapter = SoapAdapter()
        raw_input: dict[str, Any] = {
            "operation": "GetUser",
            "payload": {"id": 42},
            "headers": {"soap-action": "GetUser", "X-Request-Id": "req-1"},
        }

        exchange = await adapter.create_exchange(raw_input)

        assert isinstance(exchange, Exchange)
        assert exchange.in_message.body == {"id": 42}
        # headers: в SOAP envelope специальные ключи + кастомные.
        assert exchange.in_message.headers["soap-action"] == "GetUser"
        assert exchange.in_message.headers["soap-operation"] == "GetUser"
        assert exchange.in_message.headers["X-Request-Id"] == "req-1"
        # meta-обогащение от enrich_meta.
        assert exchange.meta.protocol == ProtocolType.soap
        assert exchange.meta.protocol_attrs["soap_operation"] == "GetUser"
        assert exchange.meta.protocol_attrs["soap_action"] == "GetUser"
        # default статус
        assert exchange.status == ExchangeStatus.pending

    async def test_minimal_input_defaults(self) -> None:
        """Минимальный/пустой raw_input: defaults — пустые строки и dict."""
        adapter = SoapAdapter()

        exchange = await adapter.create_exchange({})

        assert exchange.in_message.body == {}
        assert exchange.in_message.headers == {"soap-action": "", "soap-operation": ""}
        assert exchange.meta.protocol == ProtocolType.soap
        assert exchange.meta.protocol_attrs == {"soap_operation": "", "soap_action": ""}

    async def test_only_operation_and_payload(self) -> None:
        """Без headers — пустые ``soap-action``/``soap-operation``-производные."""
        adapter = SoapAdapter()

        exchange = await adapter.create_exchange(
            {"operation": "Ping", "payload": {"x": 1}}
        )

        assert exchange.in_message.body == {"x": 1}
        assert exchange.in_message.headers["soap-action"] == ""
        assert exchange.in_message.headers["soap-operation"] == "Ping"
        assert exchange.meta.protocol_attrs["soap_operation"] == "Ping"
        assert exchange.meta.protocol_attrs["soap_action"] == ""

    async def test_custom_soap_action_header(self) -> None:
        """Кастомный ``soap-action`` в headers попадает и в envelope, и в meta."""
        adapter = SoapAdapter()
        raw_input: dict[str, Any] = {
            "operation": "GetUser",
            "payload": {},
            "headers": {"soap-action": "http://example.com/GetUser"},
        }

        exchange = await adapter.create_exchange(raw_input)

        assert (
            exchange.in_message.headers["soap-action"] == "http://example.com/GetUser"
        )
        assert (
            exchange.meta.protocol_attrs["soap_action"] == "http://example.com/GetUser"
        )


class TestSendResponse:
    async def test_returns_out_body_when_present(self) -> None:
        """Если ``out_message`` есть, возвращаем ``out_message.body``."""
        adapter = SoapAdapter()
        exchange: Exchange[Any] = Exchange()
        exchange.set_out(body={"user_id": 7, "name": "Ivan"})

        result = await adapter.send_response(exchange, raw_context=None)
        assert result == {"user_id": 7, "name": "Ivan"}

    async def test_returns_none_when_no_out_message(self) -> None:
        """Если ``out_message is None``, возвращаем ``None``."""
        adapter = SoapAdapter()
        exchange: Exchange[Any] = Exchange()
        # out_message=None по умолчанию.

        result = await adapter.send_response(exchange, raw_context=None)
        assert result is None

    async def test_raw_context_ignored(self) -> None:
        """``raw_context`` (например, WSGI-response) — игнорируется SOAP-адаптером.

        Контракт задокументирован: ответ формируется в ``soap_handler.py``,
        адаптер возвращает только body.
        """
        adapter = SoapAdapter()
        exchange: Exchange[Any] = Exchange()
        exchange.set_out(body="ok")

        # Передача произвольного raw_context не должна влиять на результат.
        result = await adapter.send_response(exchange, raw_context={"ignored": 1})
        assert result == "ok"


class TestLifecycle:
    async def test_start_is_noop(self) -> None:
        """``start`` — async no-op (адаптер stateless)."""
        adapter = SoapAdapter()
        result = await adapter.start()
        assert result is None

    async def test_stop_is_noop(self) -> None:
        """``stop`` — async no-op (адаптер stateless)."""
        adapter = SoapAdapter()
        result = await adapter.stop()
        assert result is None
