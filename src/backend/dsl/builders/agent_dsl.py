"""Agent DSL миксин для ``RouteBuilder`` (S27 W1-W3).

Группа: agent_run / ai_invoke / agent_branch / agent_loop / agent_parallel
(W1, S27); guardrails_apply / pii_mask / pii_unmask (W2); skill_invoke /
ai_memory_recall / ai_memory_store (W3).

Контракт миксина: stateless, без ``@dataclass``, ``__slots__ = ()`` —
см. ``base.py``. Все методы используют ``self._add(...)`` через MRO.

См. ADR-NEW-19..24, docs/adr/0070-agent-dsl-processors.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("AgentDSLMixin",)


class AgentDSLMixin:
    """Поведенческий миксин Agent DSL для :class:`RouteBuilder` (S27).

    Stateless — миксин использует ``self._add`` через MRO; собственных полей
    не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

    # ── W1 — Agent primary (5 methods) ──

    def agent_run(
        self,
        *,
        workflow_id: str,
        prompt_ref: str | None = None,
        prompt_inline: str | None = None,
        policy_ref: str | None = None,
        context_property: str | None = "body",
        result_property: str = "agent_result",
    ) -> "RouteBuilder":
        """Вызов :class:`AIGateway.invoke` по ``workflow_id`` (S27 W1).

        Args:
            workflow_id: Идентификатор бизнес-операции
                (``"credit_check"``, ``"doc_summarize"``).
            prompt_ref: Ссылка на промпт в Langfuse PromptRegistry.
                Взаимоисключаемо с ``prompt_inline``.
            prompt_inline: Inline-промпт без registry-маршрутизации.
            policy_ref: Опц. ссылка на :class:`AIPolicySpec.name`
                для downstream-консумеров.
            context_property: Путь к context-переменным в exchange
                (``"body"`` / ``"body.<key>"`` / ``"property:<name>"``).
            result_property: Свойство, куда записать :class:`AIResponse`.

        Example::

            builder.agent_run(
                workflow_id="credit_check",
                prompt_ref="credit_check.production",
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.agent_run import (
            AgentRunProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            AgentRunProcessor(
                workflow_id=workflow_id,
                prompt_ref=prompt_ref,
                prompt_inline=prompt_inline,
                policy_ref=policy_ref,
                context_property=context_property,
                result_property=result_property,
            )
        )

    def ai_invoke(
        self,
        *,
        workflow_id: str,
        prompt_ref: str | None = None,
        prompt_inline: str | None = None,
        policy_ref: str | None = None,
        context_property: str | None = "body",
        result_property: str = "agent_result",
    ) -> "RouteBuilder":
        """Алиас :meth:`agent_run` — для семантически нагруженных мест
        (``.ai_invoke(workflow_id="doc_summarize")`` читается естественнее
        чем ``.agent_run(...)`` когда подразумевается одиночный LLM-вызов).
        """
        return self.agent_run(
            workflow_id=workflow_id,
            prompt_ref=prompt_ref,
            prompt_inline=prompt_inline,
            policy_ref=policy_ref,
            context_property=context_property,
            result_property=result_property,
        )

    def agent_branch(
        self,
        *,
        source_property: str,
        branches: dict[str, "list[BaseProcessor]"],
        default: "list[BaseProcessor] | None" = None,
    ) -> "RouteBuilder":
        """Verdict-based routing по ``agent_result`` (S27 W1).

        Args:
            source_property: Dot-path к значению-verdict
                (``"agent_result.content"`` /
                ``"agent_result.structured.verdict"``).
            branches: ``verdict_value`` → ``list[BaseProcessor]``.
            default: Опц. fallback-ветка.

        Example::

            builder.agent_branch(
                source_property="agent_result.structured.verdict",
                branches={
                    "approve": [DispatchActionProcessor("credit.create_offer")],
                    "reject": [DispatchActionProcessor("credit.send_rejection")],
                },
                default=[DispatchActionProcessor("credit.review_manual")],
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.agent_branch import (
            AgentBranchProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            AgentBranchProcessor(
                source_property=source_property,
                branches=branches,
                default=default,
            )
        )

    def agent_loop(
        self,
        *,
        processors: "list[BaseProcessor]",
        max_iterations: int = 5,
        stop_condition_property: str | None = None,
        budget_cost_usd: float | None = None,
        budget_tokens: int | None = None,
    ) -> "RouteBuilder":
        """Циклическое выполнение вложенного pipeline (S27 W1).

        Args:
            processors: Шаги, повторяемые на каждой итерации.
            max_iterations: Жёсткий лимит итераций.
            stop_condition_property: Опц. dot-path к флагу остановки.
            budget_cost_usd: Опц. суммарный лимит ``cost_usd``.
            budget_tokens: Опц. суммарный лимит токенов.

        Example::

            builder.agent_loop(
                processors=[AgentRunProcessor(workflow_id="followup", ...)],
                max_iterations=5,
                stop_condition_property="agent_result.structured.done",
                budget_cost_usd=0.50,
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.agent_loop import (
            AgentLoopProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            AgentLoopProcessor(
                processors=processors,
                max_iterations=max_iterations,
                stop_condition_property=stop_condition_property,
                budget_cost_usd=budget_cost_usd,
                budget_tokens=budget_tokens,
            )
        )

    def agent_parallel(
        self,
        *,
        agents: list[dict[str, Any]],
        result_property: str = "agent_parallel_results",
        timeout_s: float | None = None,
        continue_on_error: bool = True,
    ) -> "RouteBuilder":
        """Параллельный fan-out агентов через :class:`asyncio.TaskGroup` (S27 W1).

        Args:
            agents: Список dict с ``key`` + параметрами AgentRunProcessor.
            result_property: Свойство exchange для итогового dict.
            timeout_s: Опц. общий timeout.
            continue_on_error: При ``True`` — упавший агент даёт ``{"error":...}``.

        Example::

            builder.agent_parallel(
                agents=[
                    {"key": "scoring",   "workflow_id": "credit_scoring",   "prompt_inline": "..."},
                    {"key": "antifraud", "workflow_id": "credit_antifraud", "prompt_inline": "..."},
                ],
                timeout_s=30.0,
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.agent_parallel import (
            AgentParallelProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            AgentParallelProcessor(
                agents=agents,
                result_property=result_property,
                timeout_s=timeout_s,
                continue_on_error=continue_on_error,
            )
        )
