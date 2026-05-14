"""DSPy critical eval pipelines (K4 Sprint 6 Wave 2).

Назначение:
    Программирование LLM-цепочек через DSPy (Stanford) с автоматическим
    bootstrap'ом промптов из few-shot examples. Покрывает три critical
    пайплайна банка:

        * ``credit_scoring`` — оценка кредитоспособности клиента;
        * ``document_parser`` — извлечение fields из банковских документов;
        * ``rag_reranker`` — переранжирование RAG-результатов под запрос.

Принципы:
    * feature-flag ``dspy_eval_pipeline_enabled`` (default-OFF);
    * Lazy-import ``dspy`` — отсутствие SDK скипает оптимизацию;
    * Reference dataset в ``tests/integration/ai/fixtures/dspy_baseline/``;
    * ``DSPyOptimizer.compile()`` возвращает ``CompileReport`` с lift-метрикой.
"""

from __future__ import annotations

from src.backend.services.ai.dspy.optimizer import (
    BaselineDataset,
    CompileReport,
    DSPyOptimizer,
)

__all__ = (
    "DSPyOptimizer",
    "CompileReport",
    "BaselineDataset",
)
