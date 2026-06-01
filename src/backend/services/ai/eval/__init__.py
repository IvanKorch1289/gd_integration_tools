"""Inspect AI eval framework integration (K4 Sprint 6 Wave 1).

Назначение:
    Регулярная (nightly) оценка качества LLM-цепочек проекта через
    ``inspect-ai`` (UK AI Safety Institute). Покрывает knowledge QA,
    instruction-following, hallucination detection, safety classifier,
    context-recall (RAG), tool-use и multi-turn coherence сценарии.

Принципы:
    * Все suite — независимые модули в ``services/ai/eval/suites/``;
    * CLI ``manage.py ai-eval nightly`` запускает всё подряд;
    * Артефакты складываются в ``artifacts/inspect-ai/<date>/``;
    * Управляется feature-flag ``inspect_ai_eval_enabled`` (default-OFF);
    * При отсутствии ``inspect-ai`` SDK (extra ``ai``) — InspectRunner
      возвращает скип-сообщения вместо падения.

Public API:
    * :class:`InspectRunner` — оркестратор запуска suite.
    * :data:`REFERENCE_SUITES` — реестр default-suite.
"""

from __future__ import annotations

from src.backend.services.ai.eval.inspect_runner import (
    InspectRunner,
    SuiteResult,
    SuiteSummary,
)
from src.backend.services.ai.eval.ragas_evaluator import (
    DEFAULT_THRESHOLDS,
    RAGASEvaluator,
    RAGASMetric,
    RAGASRecord,
    RAGASReport,
    get_ragas_evaluator,
)
from src.backend.services.ai.eval.suites import REFERENCE_SUITES

__all__ = (
    "InspectRunner",
    "SuiteResult",
    "SuiteSummary",
    "REFERENCE_SUITES",
    "RAGASRecord",
    "RAGASMetric",
    "RAGASReport",
    "RAGASEvaluator",
    "DEFAULT_THRESHOLDS",
    "get_ragas_evaluator",
)
