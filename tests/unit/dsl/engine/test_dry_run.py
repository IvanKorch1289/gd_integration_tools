"""Unit-тесты для dry-run executor (S10 K3 W4)."""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.dry_run import (
    StepResult,
    dry_run_route,
    waterfall_lines,
)


def test_dry_run_empty_route_zero_total() -> None:
    r = dry_run_route({"route_id": "x", "steps": []})
    assert r.total_ms == 0.0
    assert r.steps == []


def test_dry_run_returns_step_per_yaml_step() -> None:
    route = {
        "route_id": "x",
        "steps": [
            {"call_function": {"ref": "m:f"}},
            {"http_call": {"url": "https://api/x"}},
            {"audit": {"action": "ok"}},
        ],
    }
    r = dry_run_route(route, seed=42)
    assert len(r.steps) == 3
    assert [s.label for s in r.steps] == [
        "call_function",
        "http_call",
        "audit",
    ]
    assert r.total_ms > 0


def test_dry_run_is_deterministic_with_seed() -> None:
    route = {"steps": [{"http_call": {}}, {"call_function": {}}]}
    a = dry_run_route(route, seed=7)
    b = dry_run_route(route, seed=7)
    assert [s.duration_ms for s in a.steps] == [
        s.duration_ms for s in b.steps
    ]


def test_dry_run_unknown_step_records_note() -> None:
    r = dry_run_route({"steps": [{"weird_step": {}}]}, seed=1)
    assert r.steps[0].notes  # содержит "unknown step"


def test_waterfall_lines_show_relative_bars() -> None:
    route = {
        "steps": [
            {"log": {}},  # быстрый
            {"llm_call": {}},  # медленный
        ]
    }
    r = dry_run_route(route, seed=1)
    lines = waterfall_lines(r, width=10)
    assert len(lines) == 2
    # Самый длинный шаг должен иметь больше блоков.
    long_step = max(r.steps, key=lambda s: s.duration_ms).index
    long_line = lines[long_step]
    assert long_line.count("█") >= max(1, lines[1 - long_step].count("█"))


def test_step_result_dataclass() -> None:
    s = StepResult(index=0, label="a", duration_ms=12.5, output_preview="ok")
    assert s.label == "a"
    assert s.notes == []
