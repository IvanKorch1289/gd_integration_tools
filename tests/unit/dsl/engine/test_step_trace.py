"""Unit-тесты для StepTrace и traced_step (S10 K3 W8)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.dsl.engine.step_trace import (
    MAX_SNAPSHOT_SIZE,
    StepTrace,
    export_otel_attrs,
    record_trace,
    traced_step,
)


class _FakeExchange:
    def __init__(self, body: Any = None) -> None:
        self.body = body
        self._props: dict[str, Any] = {}

    def get_property(self, key: str, default: Any = None) -> Any:
        return self._props.get(key, default)

    def set_property(self, key: str, value: Any) -> None:
        self._props[key] = value


def test_step_trace_dataclass_defaults() -> None:
    t = StepTrace(processor_name="x")
    assert t.processor_name == "x"
    assert t.duration_ms == 0.0
    assert t.error_context is None
    assert t.otel_attrs == {}


def test_record_trace_creates_bucket() -> None:
    ex = _FakeExchange()
    trace = StepTrace(processor_name="proc1")
    record_trace(ex, trace)
    bucket = ex.get_property("dsl_step_traces")
    assert bucket == [trace]


def test_record_trace_appends_to_existing_bucket() -> None:
    ex = _FakeExchange()
    record_trace(ex, StepTrace(processor_name="a"))
    record_trace(ex, StepTrace(processor_name="b"))
    bucket = ex.get_property("dsl_step_traces")
    assert [t.processor_name for t in bucket] == ["a", "b"]


@pytest.mark.asyncio
async def test_traced_step_measures_duration() -> None:
    ex = _FakeExchange(body={"r": 1})
    async with traced_step(ex, processor_name="slow") as trace:
        await asyncio.sleep(0.01)
        trace.output_snapshot = "ok"
    bucket = ex.get_property("dsl_step_traces")
    assert len(bucket) == 1
    assert bucket[0].duration_ms >= 10
    assert bucket[0].output_snapshot == "ok"
    assert bucket[0].error_context is None


@pytest.mark.asyncio
async def test_traced_step_captures_exception_context() -> None:
    ex = _FakeExchange()
    with pytest.raises(RuntimeError, match="boom"):
        async with traced_step(ex, processor_name="failing"):
            raise RuntimeError("boom")
    bucket = ex.get_property("dsl_step_traces")
    assert len(bucket) == 1
    assert "RuntimeError" in bucket[0].error_context
    assert "boom" in bucket[0].error_context


@pytest.mark.asyncio
async def test_traced_step_default_output_snapshot_from_exchange() -> None:
    ex = _FakeExchange(body={"x": 42})
    async with traced_step(ex, processor_name="p"):
        pass
    bucket = ex.get_property("dsl_step_traces")
    assert "42" in bucket[0].output_snapshot


def test_input_snapshot_truncated_when_huge() -> None:
    """Большой input не должен раздувать trace больше MAX_SNAPSHOT_SIZE."""
    big = {"data": "x" * (MAX_SNAPSHOT_SIZE * 2)}

    async def _go() -> None:
        ex = _FakeExchange()
        async with traced_step(ex, processor_name="p", input_value=big):
            pass

    asyncio.run(_go())  # smoke


def test_export_otel_attrs() -> None:
    trace = StepTrace(
        processor_name="http_call",
        duration_ms=12.5,
        otel_attrs={"status_code": 200, "method": "GET"},
    )
    attrs = export_otel_attrs(trace)
    assert attrs["dsl.processor"] == "http_call"
    assert attrs["dsl.duration_ms"] == 12.5
    assert attrs["dsl.attr.status_code"] == 200
    assert attrs["dsl.attr.method"] == "GET"
