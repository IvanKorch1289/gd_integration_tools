"""Tests for src.backend.dsl.engine.step_trace."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.step_trace import (
    MAX_SNAPSHOT_SIZE,
    StepTrace,
    _truncate,
    export_otel_attrs,
    record_trace,
    traced_step,
)


@pytest.mark.unit
class TestTruncate:
    def test_short_value_unchanged(self) -> None:
        value = "hello"
        assert _truncate(value) == "'hello'"

    def test_long_value_truncated(self) -> None:
        value = "x" * (MAX_SNAPSHOT_SIZE + 10)
        result = _truncate(value)
        assert len(result) <= MAX_SNAPSHOT_SIZE
        assert result.endswith("...")

    def test_none_value(self) -> None:
        assert _truncate(None) == "None"

    def test_dict_value(self) -> None:
        value = {"key": "val"}
        assert _truncate(value) == "{'key': 'val'}"


@pytest.mark.unit
class TestStepTrace:
    def test_defaults(self) -> None:
        trace = StepTrace(processor_name="test")
        assert trace.processor_name == "test"
        assert trace.input_snapshot == ""
        assert trace.output_snapshot == ""
        assert trace.duration_ms == 0.0
        assert trace.error_context is None
        assert trace.otel_attrs == {}

    def test_to_dict(self) -> None:
        trace = StepTrace(
            processor_name="p1",
            input_snapshot="in",
            output_snapshot="out",
            duration_ms=12.5,
            error_context="err",
            otel_attrs={"k": "v"},
        )
        d = trace.to_dict()
        assert d["processor_name"] == "p1"
        assert d["duration_ms"] == 12.5
        assert d["error_context"] == "err"


@pytest.mark.unit
class TestRecordTrace:
    def test_creates_list_if_missing(self) -> None:
        exchange = MagicMock()
        exchange.get_property.return_value = None
        trace = StepTrace(processor_name="p1")
        record_trace(exchange, trace)
        exchange.set_property.assert_called_once()
        name, args, kwargs = exchange.set_property.mock_calls[0]
        assert args[0] == "dsl_step_traces"
        assert isinstance(args[1], list)
        assert args[1][0] is trace

    def test_appends_to_existing_list(self) -> None:
        exchange = MagicMock()
        existing: list[Any] = []
        exchange.get_property.return_value = existing
        trace = StepTrace(processor_name="p1")
        record_trace(exchange, trace)
        exchange.set_property.assert_not_called()
        assert existing == [trace]


@pytest.mark.unit
class TestTracedStep:
    @pytest.mark.asyncio
    async def test_successful_step(self) -> None:
        exchange = MagicMock()
        exchange.body = "response_body"

        async with traced_step(
            exchange, processor_name="http_call", input_value="req"
        ) as trace:
            trace.output_snapshot = "custom_out"

        assert trace.processor_name == "http_call"
        assert trace.input_snapshot == "'req'"
        assert trace.output_snapshot == "custom_out"
        assert trace.duration_ms >= 0
        assert trace.error_context is None

    @pytest.mark.asyncio
    async def test_step_with_exception(self) -> None:
        exchange = MagicMock()

        with pytest.raises(ValueError, match="boom"):
            async with traced_step(exchange, processor_name="proc") as trace:
                raise ValueError("boom")

        assert trace.error_context == "ValueError: boom"
        assert trace.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_step_output_fallback_to_exchange_body(self) -> None:
        exchange = MagicMock()
        exchange.body = "fallback_body"

        async with traced_step(exchange, processor_name="proc") as trace:
            pass

        assert trace.output_snapshot == "'fallback_body'"

    @pytest.mark.asyncio
    async def test_step_no_input_value(self) -> None:
        exchange = MagicMock()

        async with traced_step(exchange, processor_name="proc") as trace:
            pass

        assert trace.input_snapshot == ""


@pytest.mark.unit
class TestExportOtelAttrs:
    def test_basic_attrs(self) -> None:
        trace = StepTrace(processor_name="p1", duration_ms=10.0)
        attrs = export_otel_attrs(trace)
        assert attrs["dsl.processor"] == "p1"
        assert attrs["dsl.duration_ms"] == 10.0
        assert attrs["dsl.error"] == ""

    def test_with_error(self) -> None:
        trace = StepTrace(processor_name="p1", error_context="timeout")
        attrs = export_otel_attrs(trace)
        assert attrs["dsl.error"] == "timeout"

    def test_with_otel_attrs(self) -> None:
        trace = StepTrace(processor_name="p1", otel_attrs={"model": "gpt-4"})
        attrs = export_otel_attrs(trace)
        assert attrs["dsl.attr.model"] == "gpt-4"
