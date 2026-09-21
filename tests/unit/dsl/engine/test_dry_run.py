"""Tests for src.backend.dsl.engine.dry_run."""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.dry_run import (
    DryRunResult,
    StepResult,
    dry_run_route,
    waterfall_lines,
)


@pytest.mark.unit
class TestStepResult:
    def test_defaults(self) -> None:
        sr = StepResult(index=0, label="test", duration_ms=1.0, output_preview="ok")
        assert sr.notes == []

    def test_to_dict_not_available(self) -> None:
        # StepResult itself doesn't have to_dict; DryRunResult does
        sr = StepResult(index=0, label="test", duration_ms=1.0, output_preview="ok")
        assert sr.index == 0


@pytest.mark.unit
class TestDryRunResult:
    def test_defaults(self) -> None:
        result = DryRunResult(route_id=None)
        assert result.route_id is None
        assert result.steps == []
        assert result.total_ms == 0.0

    def test_to_dict_empty(self) -> None:
        result = DryRunResult(route_id=None)
        d = result.to_dict()
        assert d["route_id"] is None
        assert d["total_ms"] == 0.0
        assert d["steps"] == []

    def test_to_dict_with_steps(self) -> None:
        result = DryRunResult(route_id="r1")
        result.steps.append(
            StepResult(index=0, label="step1", duration_ms=5.0, output_preview="ok")
        )
        d = result.to_dict()
        assert d["route_id"] == "r1"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["label"] == "step1"


@pytest.mark.unit
class TestDryRunRoute:
    def test_empty_route(self) -> None:
        result = dry_run_route({})
        assert result.route_id is None
        assert result.steps == []
        assert result.total_ms == 0.0

    def test_route_with_processors(self) -> None:
        route = {
            "route_id": "test_route",
            "processors": [{"http_call": {}}, {"transform": {}}],
        }
        result = dry_run_route(route)
        assert result.route_id == "test_route"
        assert len(result.steps) == 2
        assert result.steps[0].label == "http_call"
        assert result.steps[1].label == "transform"
        assert result.total_ms > 0

    def test_route_with_steps_alias(self) -> None:
        route = {"route_id": "r2", "steps": [{"choice": {}}]}
        result = dry_run_route(route)
        assert len(result.steps) == 1
        assert result.steps[0].label == "choice"

    def test_deterministic_with_seed(self) -> None:
        route = {"steps": [{"http_call": {}}, {"db_query_external": {}}]}
        r1 = dry_run_route(route, seed=42)
        r2 = dry_run_route(route, seed=42)
        assert len(r1.steps) == len(r2.steps)
        for s1, s2 in zip(r1.steps, r2.steps):
            assert s1.duration_ms == s2.duration_ms

    def test_unknown_step_notes(self) -> None:
        route = {"steps": [{"unknown_xyz": {}}]}
        result = dry_run_route(route)
        assert len(result.steps) == 1
        assert any("unknown step" in n for n in result.steps[0].notes)

    def test_sample_payload_in_preview(self) -> None:
        route = {"steps": [{"log": {}}]}
        result = dry_run_route(route, sample_payload={"key": "value"})
        assert "payload_size=" in result.steps[0].output_preview

    def test_single_key_step_label(self) -> None:
        route = {"steps": [{"call_function": {"fn": "test"}}]}
        result = dry_run_route(route)
        assert result.steps[0].label == "call_function"

    def test_multi_key_step_label(self) -> None:
        route = {"steps": [{"a": 1, "b": 2}]}
        result = dry_run_route(route)
        assert result.steps[0].label == "a,b"

    def test_non_dict_step(self) -> None:
        route = {"steps": ["plain_string"]}
        result = dry_run_route(route)
        assert "plain_string" in result.steps[0].label


@pytest.mark.unit
class TestWaterfallLines:
    def test_empty_result(self) -> None:
        result = DryRunResult(route_id=None)
        assert waterfall_lines(result) == []

    def test_single_step(self) -> None:
        result = DryRunResult(route_id=None)
        result.steps.append(
            StepResult(index=0, label="s1", duration_ms=10.0, output_preview="ok")
        )
        lines = waterfall_lines(result)
        assert len(lines) == 1
        assert "s1" in lines[0]
        assert "10.00ms" in lines[0]

    def test_width_scaling(self) -> None:
        result = DryRunResult(route_id=None)
        result.steps.append(
            StepResult(index=0, label="fast", duration_ms=10.0, output_preview="ok")
        )
        result.steps.append(
            StepResult(index=1, label="slow", duration_ms=100.0, output_preview="ok")
        )
        lines = waterfall_lines(result, width=10)
        # The slower step should have more blocks
        assert len(lines) == 2

    def test_zero_duration_fallback(self) -> None:
        result = DryRunResult(route_id=None)
        result.steps.append(
            StepResult(index=0, label="zero", duration_ms=0.0, output_preview="ok")
        )
        lines = waterfall_lines(result)
        assert len(lines) == 1
        assert "0.00ms" in lines[0]
