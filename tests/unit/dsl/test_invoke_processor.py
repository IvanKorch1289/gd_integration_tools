"""Unit-тесты для DSL ``invoke``-процессора (W22.4).

Покрытие:
    * Инстанцирование (defaults / custom mode).
    * SYNC + InvocationStatus.OK → результат в body+property.
    * SYNC + InvocationStatus.ERROR → текст ошибки + exchange.stop().
    * InvocationStatus.ACCEPTED (асинхронный режим) → invocation_id в property.
    * payload_factory корректно подменяет payload.
    * to_spec() round-trip.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationResponse,
    InvocationStatus,
)
from src.dsl.engine.exchange import Exchange, Message
from src.dsl.engine.processors.invoke import InvokeProcessor


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


def _make_invoker(response: InvocationResponse) -> MagicMock:
    invoker = MagicMock()
    invoker.invoke = AsyncMock(return_value=response)
    return invoker


class TestInvokeProcessor:
    """Тесты для :class:`InvokeProcessor`."""

    def test_instantiate_defaults(self) -> None:
        proc = InvokeProcessor(action="users.list")
        assert proc.action == "users.list"
        assert proc.mode is InvocationMode.SYNC
        assert proc.result_property == "invoke_result"
        assert proc.name == "invoke:users.list"

    def test_instantiate_with_string_mode(self) -> None:
        proc = InvokeProcessor(action="users.list", mode="background")
        assert proc.mode is InvocationMode.BACKGROUND

    def test_instantiate_with_enum_mode(self) -> None:
        proc = InvokeProcessor(action="users.list", mode=InvocationMode.ASYNC_API)
        assert proc.mode is InvocationMode.ASYNC_API

    def test_instantiate_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            InvokeProcessor(action="x", mode="not-a-real-mode")

    async def test_sync_ok_writes_result(self) -> None:
        """SYNC + status=OK → result в body+property, invocation_id в property."""
        response = InvocationResponse(
            invocation_id="abc-123",
            status=InvocationStatus.OK,
            result={"items": [1, 2, 3]},
            mode=InvocationMode.SYNC,
        )
        invoker = _make_invoker(response)
        proc = InvokeProcessor(action="users.list", invoker=invoker)
        exchange = _make_exchange(body={"limit": 3})
        context = MagicMock()

        await proc.process(exchange, context)

        invoker.invoke.assert_awaited_once()
        request = invoker.invoke.call_args[0][0]
        assert request.action == "users.list"
        assert request.payload == {"limit": 3}
        assert request.mode is InvocationMode.SYNC

        assert exchange.get_property("invocation_id") == "abc-123"
        assert exchange.get_property("invoke_result") == {"items": [1, 2, 3]}
        assert exchange.out_message is not None
        assert exchange.out_message.body == {"items": [1, 2, 3]}

    async def test_sync_error_stops_exchange(self) -> None:
        """ERROR-статус → текст ошибки в property и exchange.stop()."""
        response = InvocationResponse(
            invocation_id="bad-id",
            status=InvocationStatus.ERROR,
            error="boom",
            mode=InvocationMode.SYNC,
        )
        invoker = _make_invoker(response)
        proc = InvokeProcessor(action="users.list", invoker=invoker)
        exchange = _make_exchange(body={})
        context = MagicMock()

        await proc.process(exchange, context)

        assert exchange.get_property("invoke_result") == {"error": "boom"}
        # exchange.stop() ставит property _stopped=True (cooperative stop);
        # последующие процессоры pipeline увидят флаг и не выполнятся.
        assert exchange.get_property("_stopped") is True
        assert exchange.out_message is None

    async def test_accepted_writes_invocation_id(self) -> None:
        """ACCEPTED-статус → body не меняется, invocation_id доступен."""
        response = InvocationResponse(
            invocation_id="async-1",
            status=InvocationStatus.ACCEPTED,
            mode=InvocationMode.BACKGROUND,
        )
        invoker = _make_invoker(response)
        proc = InvokeProcessor(
            action="orders.process", mode="background", invoker=invoker
        )
        exchange = _make_exchange(body={"order_id": 42})
        context = MagicMock()

        await proc.process(exchange, context)

        assert exchange.get_property("invocation_id") == "async-1"
        result = exchange.get_property("invoke_result")
        assert result == {"accepted": True, "invocation_id": "async-1"}
        # body остаётся как был — out_message не установлен
        assert exchange.out_message is None

    async def test_payload_factory_overrides_body(self) -> None:
        """payload_factory полностью заменяет payload запроса."""
        response = InvocationResponse(
            invocation_id="x",
            status=InvocationStatus.OK,
            result=None,
            mode=InvocationMode.SYNC,
        )
        invoker = _make_invoker(response)
        proc = InvokeProcessor(
            action="x.y",
            payload_factory=lambda exch: {"forced": True},
            invoker=invoker,
        )
        exchange = _make_exchange(body={"will-be": "ignored"})
        context = MagicMock()

        await proc.process(exchange, context)

        request = invoker.invoke.call_args[0][0]
        assert request.payload == {"forced": True}

    async def test_non_dict_body_becomes_empty_payload(self) -> None:
        """Если body не dict, payload по умолчанию пустой dict."""
        response = InvocationResponse(
            invocation_id="x",
            status=InvocationStatus.OK,
            mode=InvocationMode.SYNC,
        )
        invoker = _make_invoker(response)
        proc = InvokeProcessor(action="x.y", invoker=invoker)
        exchange = _make_exchange(body="raw-string")
        context = MagicMock()

        await proc.process(exchange, context)

        request = invoker.invoke.call_args[0][0]
        assert request.payload == {}

    def test_to_spec_minimal(self) -> None:
        proc = InvokeProcessor(action="users.list")
        spec = proc.to_spec()
        assert spec == {"invoke": {"action": "users.list", "mode": "sync"}}

    def test_to_spec_full(self) -> None:
        proc = InvokeProcessor(
            action="users.list",
            mode="async-api",
            reply_channel="api",
            result_property="custom",
            invocation_id_property="ticket",
        )
        spec = proc.to_spec()
        assert spec == {
            "invoke": {
                "action": "users.list",
                "mode": "async-api",
                "reply_channel": "api",
                "result_property": "custom",
                "invocation_id_property": "ticket",
            }
        }
