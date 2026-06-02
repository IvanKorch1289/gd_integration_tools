"""DSPy feedback trainer (Sprint 11 K4 W5).

Запускает BootstrapFewShot оптимизацию по labeled feedback и публикует
итоговый prompt в LangfusePromptStorage. Все ML-зависимости lazy-import —
без dspy-ai trainer работает в no-op режиме.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

__all__ = ("FeedbackTrainResult", "FeedbackTrainer")

logger = logging.getLogger("services.ai.dspy.feedback_trainer")


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
            import dspy  # type: ignore[import-not-found]

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
