"""Cycle 169 tests: ``LogProcessor`` + ``InfraLogWriteProcessor`` message interpolation.

DSL_AUDIT_CACHE_LOGGING_2026-10-20 §2.1, §2.2:
- ``RouteBuilder.log(level, message)`` — добавлен опциональный ``message``.
- ``LogProcessor`` — интерполяция ``${namespace.path}`` placeholders.
- ``InfraLogWriteProcessor`` — была docstring mismatch (literal vs interpolation).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.core import LogProcessor
from src.backend.dsl.engine.processors.infra_log import InfraLogWriteProcessor


class CapturingHandler(logging.Handler):
    """Handler, который собирает все log records."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
async def pipeline_logger() -> AsyncIterator[CapturingHandler]:
    """Yield CapturingHandler для ``dsl.pipeline`` logger."""
    handler = CapturingHandler()
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("dsl.pipeline")
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)


@pytest.fixture
async def infra_logger() -> CapturingHandler:
    """Yield CapturingHandler для ``dsl.infra_log`` logger."""
    handler = CapturingHandler()
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("dsl.infra_log")
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)


class TestLogProcessorMessage:
    async def test_legacy_mode_no_message(self, pipeline_logger: CapturingHandler) -> None:
        """``message=""`` → логируется тип body + property keys (legacy)."""
        exchange = Exchange(in_message=Message(body={"foo": "bar"}, headers={}))
        exchange.set_property("key1", "value1")
        ctx = ExecutionContext(route_id="test_route")
        proc = LogProcessor(level="info", message="")

        await proc.process(exchange, ctx)

        assert len(pipeline_logger.records) == 1
        record = pipeline_logger.records[0]
        assert "Exchange[route=test_route]" in record.getMessage()
        assert "dict" in record.getMessage()  # body type
        assert "key1" in record.getMessage()  # property keys

    async def test_message_with_property_placeholder(
        self, pipeline_logger: CapturingHandler
    ) -> None:
        """``message="${properties.order_id}"`` → интерполируется."""
        exchange = Exchange(in_message=Message(body={"foo": "bar"}, headers={}))
        exchange.set_property("order_id", "ORD-123")
        ctx = ExecutionContext(route_id="test_route")
        proc = LogProcessor(level="info", message="Order ${properties.order_id}")

        await proc.process(exchange, ctx)

        assert len(pipeline_logger.records) == 1
        assert "Order ORD-123" in pipeline_logger.records[0].getMessage()

    async def test_message_with_body_placeholder(
        self, pipeline_logger: CapturingHandler
    ) -> None:
        """``message="${body.user_id}"`` → интерполируется из body."""
        exchange = Exchange(in_message=Message(body={"user_id": 42}, headers={}))
        ctx = ExecutionContext(route_id="test_route")
        proc = LogProcessor(level="info", message="User=${body.user_id}")

        await proc.process(exchange, ctx)

        assert "User=42" in pipeline_logger.records[0].getMessage()

    async def test_message_with_header_placeholder(
        self, pipeline_logger: CapturingHandler
    ) -> None:
        """``message="${header.X-Request-Id}"`` → интерполируется из headers."""
        exchange = Exchange(
            in_message=Message(body={}, headers={"X-Request-Id": "abc-123"})
        )
        ctx = ExecutionContext(route_id="test_route")
        proc = LogProcessor(level="info", message="Req=${header.X-Request-Id}")

        await proc.process(exchange, ctx)

        assert "Req=abc-123" in pipeline_logger.records[0].getMessage()

    async def test_missing_placeholder_kept_literal(
        self, pipeline_logger: CapturingHandler
    ) -> None:
        """Отсутствующий property → placeholder остаётся literal."""
        exchange = Exchange(in_message=Message(body={}, headers={}))
        ctx = ExecutionContext(route_id="test_route")
        proc = LogProcessor(level="info", message="Order=${properties.missing}")

        await proc.process(exchange, ctx)

        # Graceful degradation: placeholder остаётся literal если не резолвится.
        assert "Order=${properties.missing}" in pipeline_logger.records[0].getMessage()

    async def test_message_with_multiple_placeholders(
        self, pipeline_logger: CapturingHandler
    ) -> None:
        """Несколько placeholders в одном message — все резолвятся."""
        exchange = Exchange(in_message=Message(body={"x": "X"}, headers={}))
        exchange.set_property("y", "Y")
        proc = LogProcessor(
            level="info", message="body=${body.x} prop=${properties.y}"
        )

        await proc.process(exchange, ExecutionContext(route_id="r"))

        assert "body=X prop=Y" in pipeline_logger.records[0].getMessage()


class TestRouteBuilderLogMessage:
    """``RouteBuilder.log(level, message)`` — добавлен optional message (cycle 169)."""

    def test_log_without_message_still_works(self) -> None:
        """Backward-compat: ``log(level)`` — без message."""
        from src.backend.dsl.builders.base import RouteBuilder

        builder = RouteBuilder.from_("test", source="http:GET /test")
        result = builder.log("info")
        assert result is builder  # chainable

    def test_log_with_message(self) -> None:
        """``log(level, message)`` — message принимается без TypeError."""
        from src.backend.dsl.builders.base import RouteBuilder

        builder = RouteBuilder.from_("test", source="http:GET /test")
        result = builder.log("info", "Processing ${properties.foo}")
        assert result is builder


class TestInfraLogWriteInterpolation:
    async def test_message_interpolated(self, infra_logger: CapturingHandler) -> None:
        """``message="${properties.order_id}"`` → интерполируется.

        Cycle 169 fix: раньше ``message`` логировался literal-строкой.
        """
        exchange = Exchange(in_message=Message(body={}, headers={}))
        exchange.set_property("order_id", "ORD-456")
        ctx = ExecutionContext(route_id="r")
        proc = InfraLogWriteProcessor(level="info", message="Order=${properties.order_id}")

        await proc.process(exchange, ctx)

        assert len(infra_logger.records) == 1
        assert "Order=ORD-456" in infra_logger.records[0].getMessage()

    async def test_message_with_body_path(self, infra_logger: CapturingHandler) -> None:
        """``message="${body.foo.bar}"`` → nested path из body."""
        exchange = Exchange(
            in_message=Message(body={"foo": {"bar": "B"}}, headers={})
        )
        proc = InfraLogWriteProcessor(level="warning", message="bar=${body.foo.bar}")

        await proc.process(exchange, ExecutionContext(route_id="r"))

        assert "bar=B" in infra_logger.records[0].getMessage()

    async def test_message_literal_when_no_placeholders(
        self, infra_logger: CapturingHandler
    ) -> None:
        """Message без placeholders — логируется as-is."""
        exchange = Exchange(in_message=Message(body={}, headers={}))
        proc = InfraLogWriteProcessor(
            level="error", message="Something went wrong"
        )

        await proc.process(exchange, ExecutionContext(route_id="r"))

        assert "Something went wrong" in infra_logger.records[0].getMessage()

    async def test_missing_placeholder_kept_literal(
        self, infra_logger: CapturingHandler
    ) -> None:
        """Отсутствующий placeholder → graceful degradation."""
        exchange = Exchange(in_message=Message(body={}, headers={}))
        proc = InfraLogWriteProcessor(
            level="info", message="Order=${properties.missing}"
        )

        await proc.process(exchange, ExecutionContext(route_id="r"))

        assert "Order=${properties.missing}" in infra_logger.records[0].getMessage()