#!/usr/bin/env python3
"""RAGAS evaluator CLI (Wave 6 GAP-AI, entry-point для ``make ai-rag-eval``).

Запускает batch RAGAS-evaluation на reference-датасете или на пользовательском
JSON-файле и:

* печатает таблицу метрик + threshold-проверки;
* сохраняет JSON-артефакт в ``artifacts/ragas/<UTC-timestamp>.json``;
* exit-code 0 если все метрики выше порога, 1 — иначе (CI-gate).

Usage::

    python -m tools.checks.ragas_runner                # banking samples
    python -m tools.checks.ragas_runner --dataset multi_turn
    python -m tools.checks.ragas_runner --file ./my_dataset.json
    python -m tools.checks.ragas_runner --threshold-faithfulness 0.9

JSON-формат пользовательского датасета::

    [
      {
        "question": "...",
        "answer": "...",
        "contexts": ["...", "..."],
        "ground_truth": "..."   # optional
      },
      ...
    ]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

from src.backend.services.ai.eval.datasets import BANKING_QA_SAMPLES, MULTI_TURN_SAMPLES
from src.backend.services.ai.eval.ragas_evaluator import (
    DEFAULT_THRESHOLDS,
    RAGASEvaluator,
    RAGASRecord,
    RAGASReport,
)

logger = logging.getLogger("tools.ragas_runner")

ARTIFACT_DIR = Path("artifacts/ragas")
REFERENCE_DATASETS: dict[str, tuple[RAGASRecord, ...]] = {
    "banking": BANKING_QA_SAMPLES,
    "multi_turn": MULTI_TURN_SAMPLES,
}


def _load_dataset_file(path: Path) -> list[RAGASRecord]:
    """Загрузить пользовательский JSON-датасет."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Не удалось прочитать {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise SystemExit(f"{path}: ожидается JSON-массив записей")
    records: list[RAGASRecord] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SystemExit(f"{path}[{idx}]: запись должна быть dict")
        try:
            records.append(
                RAGASRecord(
                    question=str(item["question"]),
                    answer=str(item["answer"]),
                    contexts=list(item.get("contexts", [])),
                    ground_truth=item.get("ground_truth"),
                )
            )
        except KeyError as exc:
            raise SystemExit(f"{path}[{idx}]: пропущено поле {exc}") from exc
    return records


def _parse_thresholds(args: argparse.Namespace) -> dict[str, float]:
    """Слить дефолты с переопределениями из CLI."""
    overrides: dict[str, float] = {}
    for name in DEFAULT_THRESHOLDS:
        cli_key = f"threshold_{name}"
        value = getattr(args, cli_key, None)
        if value is not None:
            overrides[name] = float(value)
    return overrides


def _print_report(report: RAGASReport) -> None:
    """Печать таблицы метрик."""
    if report.skipped:
        print(f"[SKIP] RAGAS evaluation: {report.skip_reason}", file=sys.stderr)
        return
    print(f"RAGAS report (records={report.record_count}):")
    header = f"{'metric':<24} {'value':>10} {'threshold':>12} {'status':>10}"
    print(header)
    print("-" * len(header))
    for m in report.metrics:
        status = "OK" if m.passed else "FAIL"
        print(f"{m.name:<24} {m.value:>10.4f} {m.threshold:>12.4f} {status:>10}")
    if report.errors:
        print("\nErrors:", file=sys.stderr)
        for e in report.errors:
            print(f"  - {e}", file=sys.stderr)


def _save_artifact(report: RAGASReport, dataset_name: str) -> Path:
    """Сохранить JSON-артефакт."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACT_DIR / f"{timestamp}-{dataset_name}.json"
    payload: dict[str, Any] = {
        "timestamp": timestamp,
        "dataset": dataset_name,
        **report.to_dict(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def _run(records: list[RAGASRecord], thresholds: dict[str, float]) -> RAGASReport:
    evaluator = RAGASEvaluator(thresholds=thresholds)
    return await evaluator.evaluate(records)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="RAGAS evaluator for ai-rag-eval CI gate"
    )
    parser.add_argument(
        "--dataset",
        choices=tuple(REFERENCE_DATASETS),
        default="banking",
        help="Reference dataset (default: banking)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Custom JSON dataset (overrides --dataset)",
    )
    parser.add_argument(
        "--no-artifact",
        action="store_true",
        help="Не сохранять JSON-артефакт в artifacts/ragas/",
    )
    for name, default in DEFAULT_THRESHOLDS.items():
        parser.add_argument(
            f"--threshold-{name.replace('_', '-')}",
            dest=f"threshold_{name}",
            type=float,
            default=None,
            help=f"Override threshold for {name} (default: {default})",
        )

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.file:
        records = _load_dataset_file(args.file)
        dataset_name = args.file.stem
    else:
        records = list(REFERENCE_DATASETS[args.dataset])
        dataset_name = args.dataset

    thresholds = _parse_thresholds(args)
    report = asyncio.run(_run(records, thresholds))

    _print_report(report)

    if not args.no_artifact:
        try:
            path = _save_artifact(report, dataset_name)
            print(f"\nArtifact: {path}", file=sys.stderr)
        except OSError as exc:
            print(f"[WARN] Artifact write failed: {exc}", file=sys.stderr)

    if report.is_blocking():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
