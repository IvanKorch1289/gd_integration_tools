"""Unit tests for ResponseValidatorProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.validate_response import (
    ResponseValidatorProcessor,
)


def _ex(body: Any = None, out_body: Any = None) -> Exchange[Any]:
    ex = Exchange(in_message=Message(body=body, headers={}))
    if out_body is not None:
        ex.set_out(body=out_body)
    return ex


class _DummyModel(BaseModel):
    name: str
    age: int


class TestResponseValidatorProcessor:
    def test_init_invalid_on_error(self) -> None:
        with pytest.raises(ValueError, match="on_error must be one of"):
            ResponseValidatorProcessor(on_error="invalid")

    def test_resolve_schema_none(self) -> None:
        proc = ResponseValidatorProcessor(schema=None)
        assert proc._resolve_schema() is None

    def test_resolve_schema_class(self) -> None:
        proc = ResponseValidatorProcessor(schema=_DummyModel)
        assert proc._resolve_schema() is _DummyModel

    def test_resolve_body_out(self) -> None:
        proc = ResponseValidatorProcessor(source="out_body")
        ex = _ex(body={"a": 1}, out_body={"b": 2})
        assert proc._resolve_body(ex) == {"b": 2}

    def test_resolve_body_in_fallback(self) -> None:
        proc = ResponseValidatorProcessor(source="out_body")
        ex = _ex(body={"a": 1})
        assert proc._resolve_body(ex) == {"a": 1}

    def test_resolve_body_in_explicit(self) -> None:
        proc = ResponseValidatorProcessor(source="in_body")
        ex = _ex(body={"a": 1}, out_body={"b": 2})
        assert proc._resolve_body(ex) == {"a": 1}

    @pytest.mark.asyncio
    async def test_process_no_schema_noop(self) -> None:
        proc = ResponseValidatorProcessor(schema=None)
        ex = _ex(body={})
        await proc.process(ex, None)  # type: ignore[arg-type]
        assert "response_validation_status" not in ex.properties

    @pytest.mark.asyncio
    async def test_process_valid(self) -> None:
        proc = ResponseValidatorProcessor(schema=_DummyModel)
        ex = _ex(out_body={"name": "Alice", "age": 30})
        await proc.process(ex, None)  # type: ignore[arg-type]
        assert ex.properties["response_validation_status"] == "ok"
        assert ex.properties["_validated_body"] is not None

    @pytest.mark.asyncio
    async def test_process_invalid_fail(self) -> None:
        proc = ResponseValidatorProcessor(schema=_DummyModel, on_error="fail")
        ex = _ex(out_body={"name": "Alice"})
        await proc.process(ex, None)  # type: ignore[arg-type]
        assert ex.status.name == "failed"
        assert ex.error is not None

    @pytest.mark.asyncio
    async def test_process_invalid_dlq(self) -> None:
        proc = ResponseValidatorProcessor(schema=_DummyModel, on_error="dlq")
        ex = _ex(out_body={"name": "Alice"})
        await proc.process(ex, None)  # type: ignore[arg-type]
        assert ex.properties.get("_dlq") is True
        assert "_validation_error" in ex.properties

    @pytest.mark.asyncio
    async def test_process_invalid_warn(self) -> None:
        proc = ResponseValidatorProcessor(schema=_DummyModel, on_error="warn")
        ex = _ex(out_body={"name": "Alice"})
        await proc.process(ex, None)  # type: ignore[arg-type]
        assert ex.properties.get("response_validation_status") == "warn"
        assert "_validation_error" in ex.properties

    def test_to_spec_with_class(self) -> None:
        proc = ResponseValidatorProcessor(schema=_DummyModel, on_error="warn")
        spec = proc.to_spec()
        assert spec["validate_response"]["on_error"] == "warn"
        assert "_DummyModel" in spec["validate_response"]["schema"]

    def test_to_spec_defaults(self) -> None:
        proc = ResponseValidatorProcessor()
        assert proc.to_spec() == {"validate_response": {"on_error": "fail"}}
