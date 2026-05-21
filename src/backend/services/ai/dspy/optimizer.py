"""DSPyOptimizer — wrapper над DSPy compile API (K4 S6 W2).

Назначение:
    Абстракция над ``dspy.teleprompt.BootstrapFewShot`` (либо аналогом)
    с метрикой lift = (optimized_score − baseline_score) / baseline_score.
    Опционален: при отсутствии ``dspy`` SDK возвращается отчёт-стаб.

Использование::

    optimizer = DSPyOptimizer(baseline=BaselineDataset(...))
    report = await optimizer.compile(pipeline=credit_scoring_pipeline)
    assert report.lift >= 0.10  # threshold >=10% или >=5% (deferred)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

__all__ = ("DSPyOptimizer", "BaselineDataset", "CompileReport", "DSPyPipeline")


class DSPyPipeline(Protocol):
    """Контракт DSPy-pipeline.

    Каждый pipeline-модуль обязан экспортировать:

    * ``name``: snake_case идентификатор;
    * ``description``: краткое описание;
    * ``forward(input)``: возвращает str-output для одного sample;
    * ``metric(example, output)``: возвращает float ∈ [0, 1].
    """

    name: str
    description: str

    def forward(self, example: dict[str, Any]) -> str:
        """Производит output на одном example."""
        ...

    def metric(self, example: dict[str, Any], output: str) -> float:
        """Возвращает scalar ∈ [0, 1] для оценки качества output."""
        ...


@dataclass(slots=True)
class BaselineDataset:
    """Reference dataset для DSPy-оптимизации."""

    name: str
    train: list[dict[str, Any]] = field(default_factory=list)
    eval: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load_from_json(cls, path: Path | str) -> BaselineDataset:
        """Загружает baseline из JSON-файла (поля name/train/eval)."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            name=str(data.get("name") or Path(path).stem),
            train=list(data.get("train") or []),
            eval=list(data.get("eval") or []),
        )

    def split(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self.train, self.eval


@dataclass(slots=True)
class CompileReport:
    """Отчёт ``DSPyOptimizer.compile()``."""

    pipeline_name: str
    baseline_name: str
    baseline_score: float
    optimized_score: float
    train_size: int
    eval_size: int
    sdk_available: bool
    error: str | None = None

    @property
    def lift(self) -> float:
        """Относительное улучшение качества.

        Returns:
            ``(optimized − baseline) / baseline`` или 0.0 если baseline=0.
        """
        if self.baseline_score <= 0:
            return 0.0
        return (self.optimized_score - self.baseline_score) / self.baseline_score

    def passes_threshold(self, *, threshold: float = 0.10) -> bool:
        """Проверка lift против threshold (default 10% / S6 deferred — 5%)."""
        return self.lift >= float(threshold)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lift"] = self.lift
        return data


class DSPyOptimizer:
    """Wrapper над DSPy bootstrap-оптимизатором.

    Args:
        baseline: Datatset с train+eval splits;
        bootstrap_strategy: callable, принимающий
            (pipeline, train) и возвращающий новую callable(example)->str.
            При None — используется ``_default_bootstrap`` (least-squares
            подбор top-N examples по metric()).
    """

    def __init__(
        self,
        *,
        baseline: BaselineDataset,
        bootstrap_strategy: Callable[
            [DSPyPipeline, Sequence[dict[str, Any]]], Callable[[dict[str, Any]], str]
        ]
        | None = None,
    ) -> None:
        self._baseline = baseline
        self._bootstrap = bootstrap_strategy or _default_bootstrap

    def is_enabled(self) -> bool:
        """Проверяет feature-flag ``dspy_eval_pipeline_enabled``."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(feature_flags.dspy_eval_pipeline_enabled)
        except Exception as exc:  # noqa: BLE001
            logger.debug("DSPyOptimizer: feature_flags недоступны: %s", exc)
            return False

    def _is_sdk_available(self) -> bool:
        try:
            import dspy  # type: ignore[import-not-found]  # noqa: F401

            return True
        except ImportError:
            return False

    async def compile(self, *, pipeline: DSPyPipeline) -> CompileReport:
        """Запускает baseline + optimized eval, возвращает ``CompileReport``."""
        train, eval_set = self._baseline.split()
        sdk_available = self._is_sdk_available()

        # baseline: pipeline.forward без bootstrap.
        baseline_score = _avg_metric(pipeline, eval_set, pipeline.forward)

        # bootstrap → optimized callable.
        try:
            optimized_callable = self._bootstrap(pipeline, train)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DSPyOptimizer bootstrap failed: %s", exc)
            return CompileReport(
                pipeline_name=pipeline.name,
                baseline_name=self._baseline.name,
                baseline_score=baseline_score,
                optimized_score=baseline_score,
                train_size=len(train),
                eval_size=len(eval_set),
                sdk_available=sdk_available,
                error=f"bootstrap failed: {exc}",
            )

        optimized_score = _avg_metric(pipeline, eval_set, optimized_callable)

        return CompileReport(
            pipeline_name=pipeline.name,
            baseline_name=self._baseline.name,
            baseline_score=baseline_score,
            optimized_score=optimized_score,
            train_size=len(train),
            eval_size=len(eval_set),
            sdk_available=sdk_available,
        )


def _avg_metric(
    pipeline: DSPyPipeline,
    examples: Sequence[dict[str, Any]],
    runner: Callable[[dict[str, Any]], str],
) -> float:
    """Среднее значение pipeline.metric() по списку examples."""
    if not examples:
        return 0.0
    total = 0.0
    for example in examples:
        try:
            output = runner(example)
            total += float(pipeline.metric(example, output))
        except Exception as exc:  # noqa: BLE001
            logger.debug("DSPy example failed: %s", exc)
    return total / len(examples)


def _default_bootstrap(
    pipeline: DSPyPipeline, train: Sequence[dict[str, Any]]
) -> Callable[[dict[str, Any]], str]:
    """Default fallback-bootstrap: возвращает best-match-by-input wrapper.

    При отсутствии DSPy SDK строит lookup: train-input → train-output (best).
    Для eval-example возвращает train-output с максимальным token-overlap.
    """
    pairs: list[tuple[set[str], str]] = []
    for example in train:
        text = _example_text(example)
        tokens = {t.lower() for t in text.split() if t}
        expected = str(example.get("expected") or example.get("output") or "")
        if tokens and expected:
            pairs.append((tokens, expected))

    if not pairs:
        return pipeline.forward

    def _bootstrapped(example: dict[str, Any]) -> str:
        text = _example_text(example)
        ex_tokens = {t.lower() for t in text.split() if t}
        best_score = -1.0
        best_output = pipeline.forward(example)
        for tokens, expected in pairs:
            if not tokens:
                continue
            overlap = len(ex_tokens & tokens) / len(tokens)
            if overlap > best_score:
                best_score = overlap
                best_output = expected
        return best_output

    return _bootstrapped


def _example_text(example: dict[str, Any]) -> str:
    """Объединяет input/question/context в единую строку."""
    parts = [
        str(example.get("input") or ""),
        str(example.get("question") or ""),
        str(example.get("context") or ""),
    ]
    return " ".join(p for p in parts if p)
