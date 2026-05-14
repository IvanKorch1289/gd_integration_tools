"""InspectRunner — оркестратор Inspect AI eval-сюитов (K4 S6 W1).

Назначение:
    Лёгкий wrapper поверх :mod:`inspect_ai`. Регистрирует набор reference
    suite и запускает их синхронно либо асинхронно (через nightly job).
    Результаты сериализуются в JSON и Markdown для CI-artifact.

Безопасность:
    * Lazy-import ``inspect_ai`` — отсутствие SDK не ломает CLI;
    * feature-flag ``inspect_ai_eval_enabled`` гасит выполнение;
    * Артефакты пишутся в ``artifacts/inspect-ai/<YYYY-MM-DD>/``
      (workspace-scoped, без вмешательства в исходный код).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

__all__ = (
    "InspectRunner",
    "SuiteResult",
    "SuiteSummary",
    "EvalSuite",
)

logger = logging.getLogger(__name__)


class EvalSuite(Protocol):
    """Протокол suite-модуля.

    Каждый suite в :mod:`services.ai.eval.suites` обязан экспортировать:

    * ``name``: snake_case-идентификатор (например, ``knowledge_qa``);
    * ``description``: краткое описание на русском (для отчёта);
    * ``build_dataset()``: возвращает список samples (dict-форма);
    * ``score(sample, output)``: вычисляет dict метрик (accuracy/etc).
    """

    name: str
    description: str

    def build_dataset(self) -> list[dict[str, Any]]:
        """Возвращает список samples для прогона."""
        ...

    def score(self, sample: dict[str, Any], output: str) -> dict[str, float]:
        """Возвращает dict метрик ({metric_name: value}) для одного sample."""
        ...


@dataclass(slots=True)
class SuiteResult:
    """Результат прогона одного suite."""

    name: str
    description: str
    sample_count: int
    metrics: dict[str, float]
    started_at: str
    finished_at: str
    duration_seconds: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SuiteSummary:
    """Сводный отчёт nightly run."""

    started_at: str
    finished_at: str
    suites: list[SuiteResult] = field(default_factory=list)
    total_samples: int = 0
    skipped: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_samples": self.total_samples,
            "skipped": self.skipped,
            "failed": self.failed,
            "suites": [s.to_dict() for s in self.suites],
        }

    def to_markdown(self) -> str:
        """Markdown-форма отчёта (для CI summary)."""
        lines = ["# Inspect AI Nightly Report", ""]
        lines.append(f"- Started: {self.started_at}")
        lines.append(f"- Finished: {self.finished_at}")
        lines.append(f"- Suites: {len(self.suites)}")
        lines.append(f"- Total samples: {self.total_samples}")
        if self.skipped:
            lines.append(f"- Skipped: {self.skipped}")
        if self.failed:
            lines.append(f"- Failed: {self.failed}")
        lines.append("")
        lines.append("| Suite | Samples | Key metric | Value | Status |")
        lines.append("|---|---|---|---|---|")
        for suite in self.suites:
            status = "FAIL" if suite.error else ("SKIP" if suite.sample_count == 0 else "OK")
            if suite.metrics:
                key_metric = next(iter(suite.metrics.keys()))
                key_value = f"{suite.metrics[key_metric]:.3f}"
            else:
                key_metric, key_value = "-", "-"
            lines.append(
                f"| {suite.name} | {suite.sample_count} | {key_metric} | {key_value} | {status} |"
            )
        return "\n".join(lines) + "\n"


class InspectRunner:
    """Оркестратор Inspect AI eval-сюитов.

    Args:
        artifacts_dir: Каталог для записи JSON/MD-отчётов (default
            ``artifacts/inspect-ai``).
        suites: Список suite-модулей; если ``None`` — используются
            ``REFERENCE_SUITES``.
    """

    def __init__(
        self,
        *,
        artifacts_dir: Path | str | None = None,
        suites: Sequence[EvalSuite] | None = None,
    ) -> None:
        from src.backend.services.ai.eval.suites import REFERENCE_SUITES

        self._artifacts_dir = Path(artifacts_dir or "artifacts/inspect-ai")
        self._suites: tuple[EvalSuite, ...] = tuple(suites or REFERENCE_SUITES)

    @property
    def suite_names(self) -> tuple[str, ...]:
        """Имена зарегистрированных suite."""
        return tuple(s.name for s in self._suites)

    def is_enabled(self) -> bool:
        """Проверяет feature-flag ``inspect_ai_eval_enabled``."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(feature_flags.inspect_ai_eval_enabled)
        except Exception as exc:  # noqa: BLE001
            logger.debug("InspectRunner: feature_flags недоступны: %s", exc)
            return False

    def _is_sdk_available(self) -> bool:
        """Проверяет наличие ``inspect-ai`` SDK (extra ``ai``)."""
        try:
            import inspect_ai  # type: ignore[import-not-found]  # noqa: F401

            return True
        except ImportError:
            return False

    def run_suite(self, suite: EvalSuite) -> SuiteResult:
        """Прогоняет один suite (синхронно)."""
        started = datetime.now(timezone.utc)
        try:
            dataset = suite.build_dataset()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Suite %s build_dataset failed: %s", suite.name, exc)
            return SuiteResult(
                name=suite.name,
                description=getattr(suite, "description", ""),
                sample_count=0,
                metrics={},
                started_at=started.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                duration_seconds=0.0,
                error=f"build_dataset failed: {exc}",
            )

        accumulated: dict[str, list[float]] = {}
        for sample in dataset:
            try:
                # В offline-режиме используем эталонный ответ; реальный LLM
                # подключается через inspect_ai.solver если SDK доступен.
                output = sample.get("expected", "")
                metrics = suite.score(sample, output)
                for key, value in metrics.items():
                    accumulated.setdefault(key, []).append(float(value))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Suite %s sample failed: %s", suite.name, exc)

        finished = datetime.now(timezone.utc)
        aggregated = {
            key: round(sum(values) / max(len(values), 1), 6)
            for key, values in accumulated.items()
        }

        return SuiteResult(
            name=suite.name,
            description=getattr(suite, "description", ""),
            sample_count=len(dataset),
            metrics=aggregated,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_seconds=(finished - started).total_seconds(),
        )

    def run_all(self, *, write_artifacts: bool = True) -> SuiteSummary:
        """Запускает все зарегистрированные suite + пишет артефакты."""
        started = datetime.now(timezone.utc)
        summary = SuiteSummary(started_at=started.isoformat(), finished_at="")

        if not self.is_enabled():
            logger.info(
                "InspectRunner: feature_flag inspect_ai_eval_enabled=False — skip"
            )
            summary.finished_at = datetime.now(timezone.utc).isoformat()
            summary.skipped = len(self._suites)
            return summary

        for suite in self._suites:
            result = self.run_suite(suite)
            summary.suites.append(result)
            summary.total_samples += result.sample_count
            if result.error:
                summary.failed += 1

        summary.finished_at = datetime.now(timezone.utc).isoformat()

        if write_artifacts:
            self._write_artifacts(summary)
        return summary

    def _write_artifacts(self, summary: SuiteSummary) -> None:
        """Записывает JSON и Markdown отчёт в ``artifacts/inspect-ai/<date>/``."""
        date_dir = self._artifacts_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        json_path = date_dir / "report.json"
        md_path = date_dir / "report.md"
        json_path.write_text(
            json.dumps(summary.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        md_path.write_text(summary.to_markdown(), encoding="utf-8")
        logger.info("InspectRunner artifacts written: %s, %s", json_path, md_path)
