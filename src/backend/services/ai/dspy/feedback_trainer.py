"""DSPy feedback trainer (Sprint 11 K4 W5).

Запускает BootstrapFewShot оптимизацию по labeled feedback и публикует
итоговый prompt в LangfusePromptStorage. Все ML-зависимости lazy-import —
без dspy-ai trainer работает в no-op режиме.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("FeedbackTrainResult", "FeedbackTrainer")

logger = get_logger("services.ai.dspy.feedback_trainer")


@dataclass(frozen=True, slots=True)
class FeedbackTrainResult:
    """Результат одного training-run.

    Attributes:
        examples_used: Кол-во примеров, попавших в обучение.
        prompt_version: Версия сохранённого prompt в Langfuse (``v{N}``).
        backend: ``dspy`` или ``noop`` (если dspy-ai не установлен).
        elapsed_seconds: Время обучения.
    """

    examples_used: int
    prompt_version: str
    backend: str
    elapsed_seconds: float


class FeedbackTrainer:
    """Оркестратор training-loop'а.

    Args:
        dataset_builder: :class:`DSPyDatasetBuilder` экземпляр.
        prompt_storage: Любой объект с методом
            ``async save(name, content, metadata) -> str`` —
            LangfusePromptStorage в production / dict-mock в тестах.
    """

    def __init__(self, dataset_builder: Any, prompt_storage: Any) -> None:
        self._dataset_builder = dataset_builder
        self._prompt_storage = prompt_storage

    async def train(
        self,
        *,
        prompt_name: str = "rag_default",
        tenant_id: str | None = None,
        limit: int = 1000,
    ) -> FeedbackTrainResult:
        """Запустить training: dataset → BootstrapFewShot → publish prompt."""
        import time

        started = time.monotonic()
        records = await self._dataset_builder.build(
            tenant_id=tenant_id, limit=limit, only_positive=True
        )
        try:
            import dspy

            examples = self._dataset_builder.to_dspy_examples(records)
            from dspy.teleprompt import BootstrapFewShot

            optimizer = BootstrapFewShot(metric=lambda *_a, **_k: 1.0)
            program = dspy.Predict("prompt -> completion")
            compiled = optimizer.compile(program, trainset=examples)
            prompt_content = str(compiled)
            backend = "dspy"
        except ImportError:
            logger.info("dspy-ai not installed — falling back to noop prompt")
            prompt_content = "\n\n".join(
                f"Q: {r.prompt}\nA: {r.completion}" for r in records[:5]
            )
            backend = "noop"

        version = await self._prompt_storage.save(
            name=prompt_name,
            content=prompt_content,
            metadata={
                "examples": len(records),
                "tenant_id": tenant_id,
                "backend": backend,
            },
        )
        elapsed = time.monotonic() - started
        return FeedbackTrainResult(
            examples_used=len(records),
            prompt_version=str(version),
            backend=backend,
            elapsed_seconds=elapsed,
        )


class DSPyFeedbackTrainer:
    """Thin wrapper над FeedbackTrainer (S171 M28-P1-3, D287).

    Pattern (D287, Ponytail): aggregating wrapper, D237 TDD-friendly.
    """

    def __init__(
        self,
        *,
        dataset_builder: Any = None,
        prompt_storage: Any = None,
    ) -> None:
        self._inner: FeedbackTrainer | None = None
        if dataset_builder is not None and prompt_storage is not None:
            self._inner = FeedbackTrainer(
                dataset_builder=dataset_builder,
                prompt_storage=prompt_storage,
            )

    def collect_feedback(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Собрать метрики из feedback items.

        Args:
            items: list of dicts with 'input', 'expected', 'actual', 'score'.

        Returns:
            {'total': int, 'correct': int, 'accuracy': float}
        """
        total = len(items)
        correct = sum(1 for it in items if it.get("score", 0) >= 1.0)
        accuracy = (correct / total) if total > 0 else 0.0
        return {"total": total, "correct": correct, "accuracy": accuracy}

    async def optimize(
        self,
        *,
        prompt_name: str = "rag_default",
        tenant_id: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Запустить prompt optimization через FeedbackTrainer.train().

        Returns:
            dict с результатом: status, examples, prompt_version, backend, elapsed.
            ``{"status": "noop", "reason": "..."}`` если trainer не сконфигурирован.
        """
        if self._inner is None:
            return {"status": "noop", "reason": "no inner trainer configured"}

        result = await self._inner.train(
            prompt_name=prompt_name, tenant_id=tenant_id, limit=limit
        )
        return {
            "status": "completed",
            "examples_used": result.examples_used,
            "prompt_version": result.prompt_version,
            "backend": result.backend,
            "elapsed_seconds": round(result.elapsed_seconds, 2),
        }
