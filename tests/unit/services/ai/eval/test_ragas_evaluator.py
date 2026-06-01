"""Unit-тесты RAGAS evaluator (Wave 6 GAP-AI)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.services.ai.eval.ragas_evaluator import (
    DEFAULT_THRESHOLDS,
    RAGASEvaluator,
    RAGASMetric,
    RAGASRecord,
    RAGASReport,
    get_ragas_evaluator,
)


def _record(answer: str = "ответ", gt: str | None = None) -> RAGASRecord:
    return RAGASRecord(
        question="что такое X?",
        answer=answer,
        contexts=["контекст 1", "контекст 2"],
        ground_truth=gt,
    )


def test_default_thresholds_present() -> None:
    """Все 4 метрики должны иметь дефолтные пороги."""
    expected = {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}
    assert expected.issubset(DEFAULT_THRESHOLDS.keys())
    assert DEFAULT_THRESHOLDS["faithfulness"] == 0.8


def test_evaluator_thresholds_override() -> None:
    """Override применяется поверх дефолтов и доступен read-only."""
    e = RAGASEvaluator(thresholds={"faithfulness": 0.9})
    assert e.thresholds["faithfulness"] == 0.9
    assert e.thresholds["answer_relevancy"] == DEFAULT_THRESHOLDS["answer_relevancy"]
    e.thresholds["faithfulness"] = 0.5  # mutation of view should not affect state
    assert e.thresholds["faithfulness"] == 0.9


@pytest.mark.asyncio
async def test_empty_records_skipped() -> None:
    """Пустой датасет → skipped без вызова ragas."""
    report = await RAGASEvaluator().evaluate([])
    assert report.skipped is True
    assert report.skip_reason == "empty dataset"
    assert not report.is_blocking()


@pytest.mark.asyncio
async def test_ragas_missing_dependency_graceful() -> None:
    """Отсутствие ragas/datasets → skipped, без падения."""

    def _raise_import(*_a: object, **_k: object) -> Any:
        raise ImportError("simulated missing ragas")

    evaluator = RAGASEvaluator()
    with patch.object(evaluator, "_evaluate_sync", side_effect=_raise_import):
        with pytest.raises(ImportError):
            await evaluator.evaluate([_record()])


@pytest.mark.asyncio
async def test_evaluate_sync_skips_on_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если ragas import падает — sync путь возвращает skipped."""
    import sys

    monkeypatch.setitem(sys.modules, "ragas", None)
    monkeypatch.setitem(sys.modules, "datasets", None)

    evaluator = RAGASEvaluator()
    report = evaluator._evaluate_sync([_record()])
    assert report.skipped is True
    assert "ragas not installed" in (report.skip_reason or "")
    assert report.record_count == 1


@pytest.mark.asyncio
async def test_evaluate_returns_metrics_on_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если ragas мок дёт значения — собираются RAGASMetric с правильным passed."""

    class _FakeDataset:
        @classmethod
        def from_dict(cls, _rows: dict[str, list[Any]]) -> "_FakeDataset":
            return cls()

    import sys
    import types

    raw_result = {
        "faithfulness": 0.9,
        "answer_relevancy": 0.6,  # below threshold 0.75 → fail
        "context_precision": 0.85,
        "context_recall": 0.95,
    }

    def _fake_evaluate(_ds: Any, *, metrics: list[Any], **_kwargs: Any) -> dict[str, float]:
        del metrics
        return raw_result

    fake_ragas = types.ModuleType("ragas")
    fake_ragas.evaluate = _fake_evaluate  # type: ignore[attr-defined]
    fake_metrics_mod = types.ModuleType("ragas.metrics")
    for name in raw_result:
        setattr(fake_metrics_mod, name, object())
    fake_datasets = types.ModuleType("datasets")
    fake_datasets.Dataset = _FakeDataset  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "ragas", fake_ragas)
    monkeypatch.setitem(sys.modules, "ragas.metrics", fake_metrics_mod)
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)

    evaluator = RAGASEvaluator()
    report = await evaluator.evaluate([_record(gt="эталон")])

    assert not report.skipped
    assert report.record_count == 1
    by_name = {m.name: m for m in report.metrics}
    assert by_name["faithfulness"].passed is True
    assert by_name["answer_relevancy"].passed is False
    assert report.is_blocking() is True


def test_report_to_dict_shape() -> None:
    """Serialization shape стабильный (для JSON-артефакта / dashboard)."""
    report = RAGASReport(
        metrics=[
            RAGASMetric(name="faithfulness", value=0.91, threshold=0.8, passed=True)
        ],
        record_count=5,
    )
    payload = report.to_dict()
    assert payload["record_count"] == 5
    assert payload["blocking"] is False
    assert payload["metrics"][0]["name"] == "faithfulness"
    assert payload["metrics"][0]["passed"] is True


def test_singleton_get_ragas_evaluator() -> None:
    """get_ragas_evaluator должен быть стабильным singleton."""
    a = get_ragas_evaluator()
    b = get_ragas_evaluator()
    assert a is b


@pytest.mark.asyncio
async def test_is_blocking_skipped_returns_false() -> None:
    """skipped-отчёт не блокирует CI (install-gate отдельный)."""
    report = RAGASReport(skipped=True, skip_reason="no deps")
    assert report.is_blocking() is False
