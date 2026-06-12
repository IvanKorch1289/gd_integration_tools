"""Unit-тесты DSPyOptimizer и critical pipelines (K4 S6 W2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.backend.services.ai.dspy import BaselineDataset, CompileReport, DSPyOptimizer


@dataclass(frozen=True, slots=True)
class _StubPipeline:
    """Echo pipeline: forward = ''; metric = exact match."""

    name: str = "stub"
    description: str = "echo stub"

    def forward(self, example: dict[str, Any]) -> str:
        return ""

    def metric(self, example: dict[str, Any], output: str) -> float:
        return 1.0 if output == str(example.get("expected") or "") else 0.0


def _force_flag(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(
        feature_flags, "dspy_eval_pipeline_enabled", value, raising=False
    )


@pytest.mark.dspy_eval
@pytest.mark.asyncio
async def test_baseline_score_zero_on_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Baseline forward = '' даёт 0.0 при metric exact-match."""
    _force_flag(monkeypatch, True)
    baseline = BaselineDataset(
        name="t1",
        train=[{"input": "a", "expected": "OK"}],
        eval=[{"input": "a", "expected": "OK"}],
    )
    optimizer = DSPyOptimizer(baseline=baseline)
    report = await optimizer.compile(pipeline=_StubPipeline())
    assert isinstance(report, CompileReport)
    assert report.baseline_score == pytest.approx(0.0)
    # Default bootstrap проверит token-overlap → подберёт expected="OK"
    assert report.optimized_score == pytest.approx(1.0)


@pytest.mark.dspy_eval
@pytest.mark.asyncio
async def test_lift_calculation(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_flag(monkeypatch, True)
    baseline = BaselineDataset(
        name="t2",
        train=[
            {"input": "hello world", "expected": "GOOD"},
            {"input": "foo bar", "expected": "BAD"},
        ],
        eval=[
            {"input": "hello", "expected": "GOOD"},
            {"input": "foo", "expected": "BAD"},
        ],
    )
    optimizer = DSPyOptimizer(baseline=baseline)
    report = await optimizer.compile(pipeline=_StubPipeline())
    # baseline=0; lift вычисляется как 0 если baseline_score=0.
    assert report.lift == 0.0
    # При baseline=0.5 и optimized=1.0 → lift=1.0
    report2 = CompileReport(
        pipeline_name="x",
        baseline_name="y",
        baseline_score=0.5,
        optimized_score=1.0,
        train_size=10,
        eval_size=5,
        sdk_available=False,
    )
    assert report2.lift == pytest.approx(1.0)
    assert report2.passes_threshold(threshold=0.10)
    assert not report2.passes_threshold(threshold=1.5)


def test_baseline_dataset_load_from_json(tmp_path: Path) -> None:
    file = tmp_path / "baseline.json"
    file.write_text(
        json.dumps(
            {
                "name": "x",
                "train": [{"input": "a"}, {"input": "b"}],
                "eval": [{"input": "c"}],
            }
        )
    )
    ds = BaselineDataset.load_from_json(file)
    assert ds.name == "x"
    assert len(ds.train) == 2
    assert len(ds.eval) == 1


@pytest.mark.asyncio
async def test_optimizer_is_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    optimizer = DSPyOptimizer(baseline=BaselineDataset(name="t"))
    _force_flag(monkeypatch, False)
    assert not optimizer.is_enabled()
    _force_flag(monkeypatch, True)
    assert optimizer.is_enabled()


def test_credit_scoring_pipeline_metric() -> None:
    from src.backend.services.ai.dspy.pipelines.credit_scoring import (
        credit_scoring_pipeline,
    )

    output = credit_scoring_pipeline.forward({"income_rub": 80000, "credit_score": 750})
    parsed = json.loads(output)
    assert parsed["decision"] in {"approve", "review", "reject"}
    # Метрика exact-match для baseline forward.
    score = credit_scoring_pipeline.metric(
        {
            "income_rub": 80000,
            "credit_score": 750,
            "expected": {"decision": "approve", "score": 750},
        },
        output,
    )
    assert 0.0 <= score <= 1.0


def test_document_parser_pipeline_metric() -> None:
    from src.backend.services.ai.dspy.pipelines.document_parser import (
        document_parser_pipeline,
    )

    output = document_parser_pipeline.forward(
        {"input": "Тестовый Тестов Тестович, паспорт 4501 234567, 15.03.1980"}
    )
    parsed = json.loads(output)
    assert parsed["passport"] == "4501 234567"
    assert parsed["dob"] == "15.03.1980"


def test_rag_reranker_metric() -> None:
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    example = {
        "query": "ставка ипотека",
        "candidates": [
            {"id": "d1", "text": "ипотека ставка низкая"},
            {"id": "d2", "text": "кредит наличными"},
        ],
        "expected_ranking": ["d1", "d2"],
    }
    output = rag_reranker_pipeline.forward(example)
    score = rag_reranker_pipeline.metric(example, output)
    assert 0.0 <= score <= 1.0


@pytest.mark.dspy_eval
@pytest.mark.asyncio
async def test_compile_report_to_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_flag(monkeypatch, True)
    baseline = BaselineDataset(
        name="x", train=[{"input": "a", "expected": "1"}], eval=[]
    )
    optimizer = DSPyOptimizer(baseline=baseline)
    report = await optimizer.compile(pipeline=_StubPipeline())
    d = report.to_dict()
    assert d["pipeline_name"] == "stub"
    assert "lift" in d


def test_critical_pipelines_registered() -> None:
    from src.backend.services.ai.dspy.pipelines import CRITICAL_PIPELINES

    names = {p.name for p in CRITICAL_PIPELINES}
    assert names == {"credit_scoring", "document_parser", "rag_reranker"}
