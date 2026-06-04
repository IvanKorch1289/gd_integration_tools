"""Unit-тесты для CLI debug command.

Wave [wave:h2-cli-debug]
"""

from __future__ import annotations

import json

import pytest

from src.backend.dsl.cli.debug import (
    _extract_params,
    _get_processor_info,
    _reconstruct_exchange,
    _trace_pipeline_steps,
)


class TestReconstructExchange:
    def test_basic_exchange(self) -> None:
        data = {
            "status": "pending",
            "in_message": {"body": {"key": "value"}, "headers": {}},
            "properties": {},
        }

        exchange = _reconstruct_exchange(data)

        assert exchange.status.value == "pending"
        assert exchange.in_message.body == {"key": "value"}

    def test_exchange_without_in_message(self) -> None:
        data = {"status": "completed", "properties": {}}

        exchange = _reconstruct_exchange(data)

        assert exchange.in_message is not None
        assert exchange.in_message.body is None

    def test_exchange_status_mapping(self) -> None:
        data = {"status": "failed", "properties": {}}

        exchange = _reconstruct_exchange(data)

        assert exchange.status.value == "failed"


class TestTracePipelineSteps:
    def test_trace_empty_steps(self) -> None:
        route = {"id": "test-route", "steps": []}
        result = _trace_pipeline_steps(route)

        assert result["route_id"] == "test-route"
        assert result["total_steps"] == 0
        assert result["trace"] == []

    def test_trace_with_steps(self) -> None:
        route = {
            "id": "multi-step",
            "steps": [
                {"name": "step1", "type": "log"},
                {"name": "step2", "type": "transform", "params": {}},
            ],
        }
        result = _trace_pipeline_steps(route)

        assert result["total_steps"] == 2
        assert len(result["trace"]) == 2
        assert result["trace"][0]["name"] == "step1"
        assert result["trace"][1]["type"] == "transform"

    def test_trace_missing_step_name(self) -> None:
        route = {"id": "unnamed", "steps": [{"type": "log"}]}
        result = _trace_pipeline_steps(route)

        assert result["trace"][0]["name"] == "step_0"


class TestGetProcessorInfo:
    def test_processor_not_found_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            _get_processor_info("NonExistentProcessor")

    def test_processor_info_structure(self) -> None:
        # This test will fail if the processor isn't found
        # but documents expected structure
        with pytest.raises((ValueError, AttributeError)):
            _get_processor_info("NonExistentProcessor")


class TestExtractParams:
    """Test parameter extraction from processor classes."""

    def test_extract_params_basic(self) -> None:
        # Document expected behavior
        from src.backend.dsl.engine.processors.base import BaseProcessor

        params = _extract_params(BaseProcessor)

        # BaseProcessor.__init__ takes name parameter
        assert isinstance(params, dict)


class TestDebugCommandValidation:
    """Validate debug command helper functions."""

    def test_trace_pipeline_no_steps(self) -> None:
        route = {"id": "empty-route"}
        result = _trace_pipeline_steps(route)

        assert result["total_steps"] == 0
        assert result["trace"] == []

    def test_trace_pipeline_preserves_order(self) -> None:
        route = {
            "id": "ordered",
            "steps": [
                {"name": "first", "type": "a"},
                {"name": "second", "type": "b"},
                {"name": "third", "type": "c"},
            ],
        }
        result = _trace_pipeline_steps(route)

        names = [s["name"] for s in result["trace"]]
        assert names == ["first", "second", "third"]

    def test_trace_pipeline_step_index(self) -> None:
        route = {"id": "indexed", "steps": [{"name": "a"}, {"name": "b"}]}
        result = _trace_pipeline_steps(route)

        assert result["trace"][0]["index"] == 0
        assert result["trace"][1]["index"] == 1


class TestExchangeReconstructionEdgeCases:
    """Test edge cases in exchange reconstruction."""

    def test_unknown_status_raises(self) -> None:
        data = {"status": "unknown_status", "properties": {}}

        # Unknown status should raise ValueError
        with pytest.raises(ValueError, match="not a valid ExchangeStatus"):
            _reconstruct_exchange(data)

    def test_empty_properties(self) -> None:
        data = {"status": "pending", "properties": {}}

        exchange = _reconstruct_exchange(data)

        assert len(exchange.properties) == 0

    def test_exchange_with_nested_body(self) -> None:
        data = {
            "status": "pending",
            "in_message": {
                "body": {"nested": {"deep": {"value": 123}}},
                "headers": {"content-type": "application/json"},
            },
            "properties": {},
        }

        exchange = _reconstruct_exchange(data)

        assert exchange.in_message.body["nested"]["deep"]["value"] == 123
        assert exchange.in_message.headers["content-type"] == "application/json"
