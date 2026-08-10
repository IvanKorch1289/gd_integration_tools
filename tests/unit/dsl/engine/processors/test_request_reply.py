"""Unit-тесты Request-Reply processors."""


from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.request_reply import (
    ReplyProcessor,
    RequestProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
async def test_request_processor_success() -> None:
    with patch(
        "src.backend.infrastructure.clients.messaging.reply_channel.ReplyChannel",
    ) as mock_cls:
        instance = AsyncMock()
        instance.request = AsyncMock(return_value={"result": "ok"})
        mock_cls.instance.return_value = instance

        proc = RequestProcessor(target_channel="events.test", timeout=5.0)
        exchange = _ex({"q": "hello"})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.properties["reply"] == {"result": "ok"}
        assert exchange.out_message.body == {"result": "ok"}
        instance.request.assert_awaited_once_with(
            target_channel="events.test",
            payload={"q": "hello"},
            timeout=5.0,
            correlation_id=None,
        )


@pytest.mark.asyncio
async def test_request_processor_custom_payload() -> None:
    with patch(
        "src.backend.infrastructure.clients.messaging.reply_channel.ReplyChannel",
    ) as mock_cls:
        instance = AsyncMock()
        instance.request = AsyncMock(return_value={"ok": True})
        mock_cls.instance.return_value = instance

        proc = RequestProcessor(
            target_channel="events.test",
            payload={"override": 1},
            result_property="resp",
        )
        exchange = _ex({"ignored": True})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.properties["resp"] == {"ok": True}
        instance.request.assert_awaited_once_with(
            target_channel="events.test",
            payload={"override": 1},
            timeout=30.0,
            correlation_id=None,
        )


@pytest.mark.asyncio
async def test_reply_processor_success() -> None:
    with patch(
        "src.backend.core.di.providers.infrastructure_locator.get_event_bus_facade_provider",
    ) as mock_get_facade:
        # CRIT-2 fix (cycle 31 retro): EventBusFacade stores underlying bus
        # as ``self._bus``, NOT ``self._broker``. The test mocks must mirror
        # this nested structure to validate the production code path.
        broker = AsyncMock()
        underlying_bus = AsyncMock()
        underlying_bus._broker = broker
        facade = AsyncMock()
        facade._bus = underlying_bus
        mock_get_facade.return_value = facade

        proc = ReplyProcessor(
            reply_channel="events.replies.abc",
            correlation_id="abc",
            payload={"answer": 42},
        )
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.properties["reply_sent"] is True
        broker.publish.assert_awaited_once()
        call_args = broker.publish.await_args
        assert call_args.kwargs["channel"] == "events.replies.abc"
        assert call_args.args[0]["correlation_id"] == "abc"
        assert call_args.args[0]["payload"] == {"answer": 42}


@pytest.mark.asyncio
async def test_reply_processor_from_exchange() -> None:
    with patch(
        "src.backend.core.di.providers.infrastructure_locator.get_event_bus_facade_provider",
    ) as mock_get_facade:
        broker = AsyncMock()
        underlying_bus = AsyncMock()
        underlying_bus._broker = broker
        facade = AsyncMock()
        facade._bus = underlying_bus
        mock_get_facade.return_value = facade

        proc = ReplyProcessor()
        exchange = _ex({"answer": 42})
        exchange.properties["reply_to"] = "events.replies.x"
        exchange.properties["correlation_id"] = "x"
        await proc.process(exchange, None)  # type: ignore[arg-type]

        broker.publish.assert_awaited_once()
        assert broker.publish.await_args.kwargs["channel"] == "events.replies.x"


@pytest.mark.asyncio
async def test_reply_processor_missing_meta() -> None:
    proc = ReplyProcessor()
    exchange = _ex({"answer": 42})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.status.name == "failed"


@pytest.mark.asyncio
async def test_reply_processor_no_broker() -> None:
    """Facade возвращается, но underlying bus не имеет _broker — fail-closed."""
    with patch(
        "src.backend.core.di.providers.infrastructure_locator.get_event_bus_facade_provider",
    ) as mock_get_facade:
        underlying_bus = AsyncMock()
        underlying_bus._broker = None
        facade = AsyncMock()
        facade._bus = underlying_bus
        mock_get_facade.return_value = facade

        proc = ReplyProcessor(reply_channel="events.replies.abc", correlation_id="abc")
        exchange = _ex({"answer": 42})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.status.name == "failed"
