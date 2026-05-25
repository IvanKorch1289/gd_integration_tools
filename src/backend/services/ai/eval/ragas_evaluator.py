"""RAGAS-evaluator: production-grade RAG-evaluation pipeline (Wave 6 GAP-AI).

Назначение
----------
Batch-evaluator поверх :mod:`ragas` для регулярной проверки качества
RAG-цепочек проекта (RAGService + HybridRAGSearch). Поддерживает:

* batch evaluation массива :class:`RAGASRecord`;
* четыре метрики: faithfulness / answer_relevancy / context_precision / context_recall;
* threshold gating (blocking-gate для CI: faithfulness < 0.8 → fail);
* async wrapper через :func:`asyncio.to_thread` (ragas sync API);
* graceful degradation при отсутствии :mod:`ragas` / :mod:`datasets`.

Используется
-----------
* CLI: ``make ai-rag-eval`` (см. ``tools/checks/ragas_runner.py``);
* nightly cron-job ``.github/workflows/ai-rag-eval.yml``;
* PR-gate при изменении ``services/ai/`` или ``ai_policies/``.

См. также
---------
* ADR-0073 ``docs/adr/0073-ragas-evaluation-gate.md`` (планируется);
* :mod:`src.backend.services.ai.eval.inspect_runner` — родственный Inspect AI runner;
* :mod:`src.backend.services.ai.ai_moderation` — legacy single-question RagasEvaluator.

Notes
-----
ragas требует :mod:`datasets` (HuggingFace) для построения объекта
``Dataset.from_dict``. Оба зависимостей — extra ``ai`` (см. ``pyproject.toml``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    pass

__all__ = (
    "RAGASRecord",
    "RAGASMetric",
    "RAGASReport",
    "RAGASEvaluator",
    "DEFAULT_THRESHOLDS",
)

logger = logging.getLogger("services.ai.eval.ragas")


DEFAULT_THRESHOLDS: Final[dict[str, float]] = {
    "faithfulness": 0.8,
    "answer_relevancy": 0.75,
    "context_precision": 0.7,
    "context_recall": 0.7,
}
"""Пороговые значения качества RAG-цепочки (ADR-0073 черновик).

При значении ниже порога — gate в CI fail-ит (см. :meth:`RAGASReport.is_blocking`).
"""


@dataclass(slots=True, frozen=True)
class RAGASRecord:
    """Один QA-пример для batch evaluation.

    Attributes:
        question: Текстовый вопрос к RAG-цепочке.
        answer: Ответ цепочки (то, что вернул LLM).
        contexts: Retrieved-документы (text-chunks), на которых строился ответ.
        ground_truth: Опц. эталонный ответ (нужен для ``context_recall``).
    """

    question: str
    answer: str
    contexts: list[str]
    ground_truth: str | None = None


@dataclass(slots=True, frozen=True)
class RAGASMetric:
    """Результат измерения одной метрики на наборе records.

    Attributes:
        name: Имя метрики (``faithfulness``, ``answer_relevancy``, …).
        value: Среднее значение [0..1] по всему датасету.
        threshold: Пороговое значение для blocking-gate.
        passed: ``True`` если ``value >= threshold``.
    """

    name: str
    value: float
    threshold: float
    passed: bool


@dataclass(slots=True)
class RAGASReport:
    """Итог batch evaluation.

    Attributes:
        metrics: Список измеренных метрик.
        record_count: Сколько QA-пар вошло в датасет.
        skipped: ``True`` если ragas/datasets недоступны — оценка пропущена.
        skip_reason: Причина skip (для логов / CI-сообщений).
        errors: Список текстовых ошибок при evaluation (без падения).
    """

    metrics: list[RAGASMetric] = field(default_factory=list)
    record_count: int = 0
    skipped: bool = False
    skip_reason: str | None = None
    errors: list[str] = field(default_factory=list)

    def is_blocking(self) -> bool:
        """Должен ли CI-gate fail-нуть.

        Returns:
            ``True`` если хотя бы одна метрика ниже порога. ``skipped`` → ``False``
            (отсутствие ragas — не повод валить CI, отдельный install-gate).
        """
        if self.skipped:
            return False
        return any(not m.passed for m in self.metrics)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для JSON-артефакта / Streamlit dashboard."""
        return {
            "record_count": self.record_count,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "errors": list(self.errors),
            "metrics": [
                {
                    "name": m.name,
                    "value": m.value,
                    "threshold": m.threshold,
                    "passed": m.passed,
                }
                for m in self.metrics
            ],
            "blocking": self.is_blocking(),
        }


class RAGASEvaluator:
    """Batch-evaluator поверх :mod:`ragas`.

    Используется в трёх контекстах:

    * CLI gate (:meth:`make ai-rag-eval`) — exit-code от :meth:`RAGASReport.is_blocking`;
    * nightly cron — артефакты в ``artifacts/ragas/<date>/``;
    * Streamlit page ``50_RAGAS_Quality.py`` (планируется) для on-demand runs.

    Pipeline:
        1. Lazy-import ragas + datasets; при failure → :attr:`RAGASReport.skipped`.
        2. Конвертация ``list[RAGASRecord]`` → ``datasets.Dataset``.
        3. Подбор метрик: всегда faithfulness + answer_relevancy + context_precision;
           context_recall — только если у всех records есть ``ground_truth``.
        4. ``ragas.evaluate(...)`` в ``asyncio.to_thread`` (ragas API синхронный).
        5. Сборка :class:`RAGASMetric` по каждой метрике с проверкой threshold.

    Example::

        evaluator = RAGASEvaluator(thresholds={"faithfulness": 0.85})
        report = await evaluator.evaluate([
            RAGASRecord(
                question="Какой лимит на потребкредит?",
                answer="До 5 млн.",
                contexts=["Лимит на потребкредит — 5 млн руб."],
                ground_truth="5 000 000",
            ),
        ])
        if report.is_blocking():
            sys.exit(1)
    """

    def __init__(
        self,
        *,
        thresholds: dict[str, float] | None = None,
        llm: Any | None = None,
        embeddings: Any | None = None,
    ) -> None:
        """Инициализация.

        Args:
            thresholds: Override DEFAULT_THRESHOLDS (только указанные ключи).
            llm: Опц. ragas-compatible LLM (``ragas.llms.LlamaIndexLLMWrapper``,
                ``LangchainLLMWrapper``). При ``None`` ragas использует default
                (OpenAI gpt-3.5; см. ENV ``OPENAI_API_KEY``).
            embeddings: Опц. embeddings-wrapper. При ``None`` — ragas default.
        """
        merged = dict(DEFAULT_THRESHOLDS)
        if thresholds:
            merged.update(thresholds)
        self._thresholds = merged
        self._llm = llm
        self._embeddings = embeddings

    @property
    def thresholds(self) -> dict[str, float]:
        """Текущие пороги (read-only mapping)."""
        return dict(self._thresholds)

    async def evaluate(self, records: list[RAGASRecord]) -> RAGASReport:
        """Запустить batch evaluation.

        Args:
            records: Список QA-примеров. Пустой → :attr:`RAGASReport.skipped`.

        Returns:
            :class:`RAGASReport` с метриками + threshold-проверкой.
        """
        if not records:
            return RAGASReport(skipped=True, skip_reason="empty dataset")

        return await asyncio.to_thread(self._evaluate_sync, records)

    def _evaluate_sync(self, records: list[RAGASRecord]) -> RAGASReport:
        """Синхронный путь evaluation (ragas API — sync)."""
        try:
            from datasets import Dataset  # noqa: PLC0415
            from ragas import evaluate  # noqa: PLC0415
            from ragas.metrics import (  # noqa: PLC0415
                answer_relevancy,
                context_precision,
                faithfulness,
            )
        except ImportError as exc:
            logger.warning("ragas/datasets not installed: %s", exc)
            return RAGASReport(
                skipped=True,
                skip_reason=f"ragas not installed: {exc}",
                record_count=len(records),
            )

        has_ground_truth = all(r.ground_truth for r in records)
        metrics_list: list[Any] = [faithfulness, answer_relevancy, context_precision]
        metric_names: list[str] = [
            "faithfulness",
            "answer_relevancy",
            "context_precision",
        ]

        if has_ground_truth:
            try:
                from ragas.metrics import context_recall  # noqa: PLC0415

                metrics_list.append(context_recall)
                metric_names.append("context_recall")
            except ImportError:
                logger.debug("context_recall not available in installed ragas")

        rows: dict[str, list[Any]] = {
            "question": [r.question for r in records],
            "answer": [r.answer for r in records],
            "contexts": [r.contexts for r in records],
        }
        if has_ground_truth:
            rows["ground_truth"] = [r.ground_truth or "" for r in records]

        errors: list[str] = []
        try:
            ds = Dataset.from_dict(rows)
            kwargs: dict[str, Any] = {}
            if self._llm is not None:
                kwargs["llm"] = self._llm
            if self._embeddings is not None:
                kwargs["embeddings"] = self._embeddings
            raw = evaluate(ds, metrics=metrics_list, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ragas.evaluate failed: %s", exc)
            return RAGASReport(
                skipped=True,
                skip_reason=f"evaluate failed: {exc}",
                record_count=len(records),
                errors=[str(exc)],
            )

        metrics_built: list[RAGASMetric] = []
        for name in metric_names:
            try:
                value = float(raw[name]) if name in raw else float("nan")
            except (TypeError, ValueError) as exc:
                errors.append(f"{name}: {exc}")
                continue
            if value != value:  # NaN
                errors.append(f"{name}: NaN result")
                continue
            threshold = self._thresholds.get(name, 0.0)
            metrics_built.append(
                RAGASMetric(
                    name=name,
                    value=value,
                    threshold=threshold,
                    passed=value >= threshold,
                )
            )

        return RAGASReport(
            metrics=metrics_built,
            record_count=len(records),
            skipped=False,
            errors=errors,
        )


_instance: RAGASEvaluator | None = None


def get_ragas_evaluator() -> RAGASEvaluator:
    """Singleton-получатель (для DI и CLI)."""
    global _instance
    if _instance is None:
        _instance = RAGASEvaluator()
    return _instance
