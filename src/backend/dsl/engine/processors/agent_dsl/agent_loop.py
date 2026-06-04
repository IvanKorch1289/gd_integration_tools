"""AgentLoopProcessor — циклический запуск агентских шагов (S27 W1).

Повторяет вложенный pipeline до достижения ``max_iterations`` или
выполнения ``stop_condition`` (булевое свойство в exchange). Опционально
прерывается по бюджету (cost_usd / tokens) — сумма по всем итерациям.

YAML контракт::

    steps:
      - agent_loop:
          max_iterations: 5
          stop_condition_property: agent_result.structured.done
          budget_cost_usd: 0.50
          processors:
            - agent_run:
                workflow_id: credit_followup
                prompt_inline: "Continue dialog with customer..."

Python контракт через :meth:`AgentDSLMixin.agent_loop`::

    builder.agent_loop(
        max_iterations=5,
        stop_condition_property="agent_result.structured.done",
        budget_cost_usd=0.50,
        processors=[AgentRunProcessor(workflow_id="credit_followup", ...)],
    )

Свойства exchange после выполнения
-----------------------------------
* ``agent_loop_iteration`` — index текущей итерации (0-based) в момент step;
* ``agent_loop_total_iterations`` — финальное число выполненных итераций;
* ``agent_loop_stop_reason`` — ``"condition"`` / ``"max_iterations"`` /
  ``"budget_cost"`` / ``"budget_tokens"``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor
from src.backend.dsl.engine.processors.base import BaseProcessor, run_sub_processors

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AgentLoopProcessor",)

_logger = logging.getLogger(__name__)


class AgentLoopProcessor(BaseAIProcessor):
    """Повтор вложенного pipeline до stop_condition / max_iterations / budget.

    Args:
        processors: Список процессоров, повторяемых на каждой итерации.
        max_iterations: Максимум итераций (обязательная защита от бесконечного
            цикла). Default ``5``.
        stop_condition_property: Опц. dot-path к свойству-флагу в exchange.
            При truthy-значении — break цикла. ``None`` = ориентир только
            на ``max_iterations`` / budget.
        budget_cost_usd: Опц. суммарный лимит в USD (сумма
            ``properties["agent_result"]["cost_usd"]`` по итерациям).
        budget_tokens: Опц. суммарный лимит prompt_tokens + completion_tokens.
        name: Имя процессора.
    """

    audit_event: ClassVar[str | None] = "ai.agent.loop"

    def __init__(
        self,
        *,
        processors: list[BaseProcessor],
        max_iterations: int = 5,
        stop_condition_property: str | None = None,
        budget_cost_usd: float | None = None,
        budget_tokens: int | None = None,
        name: str | None = None,
    ) -> None:
        if not processors:
            raise ValueError("AgentLoopProcessor: processors не может быть пустым")
        if max_iterations < 1:
            raise ValueError(
                f"AgentLoopProcessor: max_iterations должен быть >=1, "
                f"получено {max_iterations}"
            )
        super().__init__(name=name or "agent_loop")
        self.processors = list(processors)
        self.max_iterations = max_iterations
        self.stop_condition_property = stop_condition_property
        self.budget_cost_usd = budget_cost_usd
        self.budget_tokens = budget_tokens

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        total_cost = 0.0
        total_tokens = 0
        stop_reason: str = "max_iterations"
        iteration = 0

        for iteration in range(self.max_iterations):
            exchange.set_property("agent_loop_iteration", iteration)
            await run_sub_processors(self.processors, exchange, context)

            if exchange.stopped or exchange.error:
                stop_reason = "child_stopped"
                break

            if self._stop_condition_met(exchange):
                stop_reason = "condition"
                break

            total_cost = self._accumulate_cost(exchange, total_cost)
            total_tokens = self._accumulate_tokens(exchange, total_tokens)

            if self.budget_cost_usd is not None and total_cost >= self.budget_cost_usd:
                stop_reason = "budget_cost"
                _logger.info(
                    "%s: budget_cost_usd=%.4f exceeded (total=%.4f) — break",
                    self.name,
                    self.budget_cost_usd,
                    total_cost,
                )
                break
            if self.budget_tokens is not None and total_tokens >= self.budget_tokens:
                stop_reason = "budget_tokens"
                _logger.info(
                    "%s: budget_tokens=%d exceeded (total=%d) — break",
                    self.name,
                    self.budget_tokens,
                    total_tokens,
                )
                break
        else:
            iteration = self.max_iterations - 1

        exchange.set_property("agent_loop_total_iterations", iteration + 1)
        exchange.set_property("agent_loop_stop_reason", stop_reason)
        exchange.set_property("agent_loop_total_cost_usd", total_cost)
        exchange.set_property("agent_loop_total_tokens", total_tokens)

    def _stop_condition_met(self, exchange: Exchange[Any]) -> bool:
        """Проверить ``stop_condition_property`` через dot-path."""
        if self.stop_condition_property is None:
            return False
        parts = self.stop_condition_property.split(".")
        cursor: Any = exchange.get_property(parts[0])
        for part in parts[1:]:
            if cursor is None:
                return False
            if isinstance(cursor, dict):
                cursor = cursor.get(part)
            else:
                cursor = getattr(cursor, part, None)
        return bool(cursor)

    @staticmethod
    def _accumulate_cost(exchange: Exchange[Any], accumulator: float) -> float:
        """Прибавить cost из последнего ``agent_result`` (если есть)."""
        result = exchange.get_property("agent_result")
        if isinstance(result, dict):
            cost = result.get("cost_usd")
            if isinstance(cost, (int, float)):
                return accumulator + float(cost)
        return accumulator

    @staticmethod
    def _accumulate_tokens(exchange: Exchange[Any], accumulator: int) -> int:
        """Прибавить prompt+completion tokens из последнего ``agent_result``."""
        result = exchange.get_property("agent_result")
        if isinstance(result, dict):
            prompt = result.get("tokens_prompt", 0) or 0
            completion = result.get("tokens_completion", 0) or 0
            if isinstance(prompt, int) and isinstance(completion, int):
                return accumulator + prompt + completion
        return accumulator

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {
            "max_iterations": self.max_iterations,
            "processors": [p.to_spec() or {} for p in self.processors],
        }
        if self.stop_condition_property is not None:
            spec["stop_condition_property"] = self.stop_condition_property
        if self.budget_cost_usd is not None:
            spec["budget_cost_usd"] = self.budget_cost_usd
        if self.budget_tokens is not None:
            spec["budget_tokens"] = self.budget_tokens
        return {"agent_loop": spec}
