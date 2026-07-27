"""DSL processor: prompt optimization через DSPy feedback loop.

Запускает FeedbackTrainer.train() — собирает feedback dataset, оптимизирует
промпт через BootstrapFewShot, публикует результат в Langfuse.

Feature-flag: ``dspy_eval_pipeline_enabled`` (default-OFF). При OFF — no-op.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry.processor import processor

__all__ = ("OptimizePromptProcessor",)

_logger = get_logger("dsl.optimize_prompt")


@processor(
    "optimize_prompt",
    namespace="ai",
    capabilities=("ai.optimize",),
    tags=["ai", "dspy", "optimization"],
)
class OptimizePromptProcessor(BaseProcessor):
    """Запускает DSPy prompt optimization по собранному feedback.

    Args:
        prompt_name: Имя prompt для публикации в Langfuse.
        tenant_id: Tenant scope (None = global).
        limit: Максимум examples из feedback.
        result_property: Куда сохранить результат.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        prompt_name: str = "rag_default",
        tenant_id: str | None = None,
        limit: int = 1000,
        result_property: str = "_optimize_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"optimize_prompt:{prompt_name}")
        self._prompt_name = prompt_name
        self._tenant_id = tenant_id
        self._limit = limit
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Запустить optimization."""
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.dspy_eval_pipeline_enabled:
                exchange.set_property(
                    self._result_property,
                    {"status": "skipped", "reason": "dspy_eval_pipeline_enabled=False"},
                )
                return
        except Exception:
            pass

        # Lazy-resolve trainer from DI
        try:
            from src.backend.core.svcs_registry import get_service

            trainer = get_service("dspy_feedback_trainer")
            if trainer is None:
                trainer = get_service("feedback_trainer")
        except Exception as exc:
            _logger.warning("optimize_prompt: trainer not found in DI: %s", exc)
            exchange.set_property(
                self._result_property,
                {"status": "error", "reason": f"trainer not found: {exc}"},
            )
            return

        if trainer is None:
            exchange.set_property(
                self._result_property,
                {"status": "noop", "reason": "no trainer registered"},
            )
            return

        # Run optimization
        try:
            if hasattr(trainer, "optimize"):
                result = await trainer.optimize(
                    prompt_name=self._prompt_name,
                    tenant_id=self._tenant_id,
                    limit=self._limit,
                )
            elif hasattr(trainer, "train"):
                result = await trainer.train(
                    prompt_name=self._prompt_name,
                    tenant_id=self._tenant_id,
                    limit=self._limit,
                )
                result = {
                    "status": "completed",
                    "examples_used": result.examples_used,
                    "prompt_version": result.prompt_version,
                    "backend": result.backend,
                }
            else:
                result = {"status": "error", "reason": "trainer has no optimize/train method"}
        except Exception as exc:
            _logger.error("optimize_prompt failed: %s", exc)
            result = {"status": "error", "reason": str(exc)}

        exchange.set_property(self._result_property, result)
        _logger.info(
            "optimize_prompt: prompt=%s, status=%s",
            self._prompt_name,
            result.get("status"),
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "optimize_prompt": {
                "prompt_name": self._prompt_name,
                "tenant_id": self._tenant_id,
                "limit": self._limit,
                "result_property": self._result_property,
            }
        }
