"""Unit-тесты InspectRunner и reference suites (K4 S6 W1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.backend.services.ai.eval.inspect_runner import (
    InspectRunner,
    SuiteResult,
    SuiteSummary,
)


@dataclass(frozen=True, slots=True)
class _StubSuite:
    """Тестовый suite: 2 sample, accuracy=1.0 для всех."""

    name: str = "stub"
    description: str = "stub suite"

    def build_dataset(self) -> list[dict[str, Any]]:
        return [
            {"id": "s1", "expected": "hello"},
            {"id": "s2", "expected": "world"},
        ]

    def score(self, sample: dict[str, Any], output: str) -> dict[str, float]:
        return {"accuracy": 1.0 if output == sample.get("expected") else 0.0}


def _force_flag(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    """Жёстко выставляет feature_flag.inspect_ai_eval_enabled."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "inspect_ai_eval_enabled", value, raising=False)


def test_runner_disabled_when_flag_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _force_flag(monkeypatch, False)
    runner = InspectRunner(artifacts_dir=tmp_path, suites=[_StubSuite()])
    summary = runner.run_all(write_artifacts=False)
    assert summary.skipped == 1
    assert summary.total_samples == 0


def test_runner_runs_stub_suite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _force_flag(monkeypatch, True)
    runner = InspectRunner(artifacts_dir=tmp_path, suites=[_StubSuite()])
    summary = runner.run_all(write_artifacts=True)
    assert isinstance(summary, SuiteSummary)
    assert summary.total_samples == 2
    assert len(summary.suites) == 1
    res = summary.suites[0]
    assert isinstance(res, SuiteResult)
    assert res.metrics.get("accuracy") == pytest.approx(1.0)


def test_runner_writes_json_md(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _force_flag(monkeypatch, True)
    runner = InspectRunner(artifacts_dir=tmp_path, suites=[_StubSuite()])
    runner.run_all(write_artifacts=True)
    files = list(tmp_path.rglob("*.json")) + list(tmp_path.rglob("*.md"))
    assert files, "Artifacts должны быть записаны"
    json_files = [f for f in files if f.suffix == ".json"]
    assert json_files
    data = json.loads(json_files[0].read_text())
    assert "suites" in data
    assert data["total_samples"] == 2


def test_summary_markdown_format() -> None:
    summary = SuiteSummary(started_at="2026-05-14T00:00:00Z", finished_at="2026-05-14T00:01:00Z")
    summary.suites.append(
        SuiteResult(
            name="x",
            description="d",
            sample_count=3,
            metrics={"accuracy": 0.95},
            started_at="2026-05-14T00:00:00Z",
            finished_at="2026-05-14T00:01:00Z",
            duration_seconds=60.0,
        )
    )
    summary.total_samples = 3
    md = summary.to_markdown()
    assert "Inspect AI Nightly Report" in md
    assert "0.950" in md
    assert "| x |" in md


def test_reference_suites_register() -> None:
    from src.backend.services.ai.eval.suites import REFERENCE_SUITES

    names = {s.name for s in REFERENCE_SUITES}
    assert "knowledge_qa" in names
    assert "instruction_following" in names
    assert "hallucination_check" in names
    assert "safety_classifier" in names
    assert "context_recall" in names
    assert len(REFERENCE_SUITES) >= 5


@pytest.mark.parametrize(
    "suite_name,min_samples",
    [
        ("knowledge_qa", 6),
        ("instruction_following", 5),
        ("hallucination_check", 5),
        ("safety_classifier", 5),
        ("context_recall", 5),
        ("tool_use", 3),
        ("multi_turn_coherence", 3),
    ],
)
def test_reference_suite_dataset_non_empty(suite_name: str, min_samples: int) -> None:
    from src.backend.services.ai.eval.suites import REFERENCE_SUITES

    suite = next((s for s in REFERENCE_SUITES if s.name == suite_name), None)
    assert suite is not None
    dataset = suite.build_dataset()
    assert len(dataset) >= min_samples


def test_score_metrics_within_range() -> None:
    """Проверяем, что score() для эталонных suite возвращает значения в [0,1]."""
    from src.backend.services.ai.eval.suites import REFERENCE_SUITES

    for suite in REFERENCE_SUITES:
        sample = suite.build_dataset()[0]
        metrics = suite.score(sample, sample.get("expected", ""))
        assert isinstance(metrics, dict) and metrics
        for value in metrics.values():
            assert isinstance(value, (int, float))
            assert value >= 0.0
