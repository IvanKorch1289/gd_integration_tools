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





class OrchestrationMixin:
    """Поведенческий миксин orchestration для :class:`RouteBuilder` (S51 W3)."""

    __slots__ = ()

    # --- agent orchestration (agent_run, ai_invoke, agent_branch, agent_loop, agent_parallel, plan_execute, reflection_loop_workflow, hitl_approval) ---

    def agent_run(
        self,
        *,
        workflow_id: str,
        prompt_ref: str | None = None,
        prompt_inline: str | None = None,
        policy_ref: str | None = None,
        context_property: str | None = "body",
        result_property: str = "agent_result",
        timeout_s: float = 300.0,
        max_retries: int = 3,
    ) -> RouteBuilder:
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
            timeout_s: Timeout на вызов в секундах (default 300).
            max_retries: Число повторных попыток при transient failure (default 3).

        Example::

            builder.agent_run(
                workflow_id="credit_check",
                prompt_ref="credit_check.production",
                timeout_s=120,
                max_retries=3,
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
                timeout_s=timeout_s,
                max_retries=max_retries,
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
    ) -> RouteBuilder:
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
        branches: dict[str, list[BaseProcessor]],
        default: list[BaseProcessor] | None = None,
    ) -> RouteBuilder:
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
                source_property=source_property, branches=branches, default=default
            )
        )



    def agent_loop(
        self,
        *,
        processors: list[BaseProcessor],
        max_iterations: int = 5,
        stop_condition_property: str | None = None,
        budget_cost_usd: float | None = None,
        budget_tokens: int | None = None,
    ) -> RouteBuilder:
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
    ) -> RouteBuilder:
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



    def plan_execute(
        self,
        *,
        planner_workflow_id: str,
        executor_workflow_id: str,
        verifier_workflow_id: str,
        max_replans: int = 3,
        plan_output_property: str = "plan",
        result_property: str = "plan_execute_result",
        timeout_s: float = 300.0,
    ) -> RouteBuilder:
        """Plan-and-Execute agentic pattern с verification + replan (S39 W2).

        LLM генерирует план (список шагов) → каждый шаг выполняется через
        executor → verifier проверяет результат. При ``fail`` — replan
        с контекстом ошибок (до ``max_replans``).

        Args:
            planner_workflow_id: workflow_id для генерации плана.
            executor_workflow_id: workflow_id для выполнения шага.
            verifier_workflow_id: workflow_id для верификации результата.
            max_replans: Максимум попыток перепланировать. Default ``3``.
            plan_output_property: Свойство для сохранения плана.
            result_property: Свойство для финального результата.
            timeout_s: Таймаут на один LLM-вызов. Default ``300``.

        Example::

            builder.plan_execute(
                planner_workflow_id="generate_plan",
                executor_workflow_id="execute_step",
                verifier_workflow_id="verify_step",
                max_replans=3,
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.plan_execute import (
            PlanExecuteProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            PlanExecuteProcessor(
                planner_workflow_id=planner_workflow_id,
                executor_workflow_id=executor_workflow_id,
                verifier_workflow_id=verifier_workflow_id,
                max_replans=max_replans,
                plan_output_property=plan_output_property,
                result_property=result_property,
                timeout_s=timeout_s,
            )
        )



    def reflection_loop_workflow(
        self,
        *,
        generator_workflow_id: str,
        reflector_workflow_id: str,
        refiner_workflow_id: str | None = None,
        max_iterations: int = 3,
        stop_verdict: str = "ok",
        result_property: str = "reflection_result",
        history_property: str | None = "reflection_history",
        timeout_s: float = 300.0,
    ) -> RouteBuilder:
        """Generate → Reflect → Refine agentic pattern via workflows (S39 W3).

        LLM генерирует draft → reflector оценивает и возвращает
        ``verdict`` + ``critique`` → refiner улучшает draft.
        Цикл останавливается при ``verdict == stop_verdict``
        или после ``max_iterations``.

        Args:
            generator_workflow_id: workflow_id для генерации начального draft.
            reflector_workflow_id: workflow_id для критики draft.
            refiner_workflow_id: workflow_id для улучшения draft.
                Default ``None`` — используется ``generator_workflow_id``.
            max_iterations: Максимум итераций reflection + refine. Default ``3``.
            stop_verdict: Значение verdict для остановки. Default ``"ok"``.
            result_property: Свойство для финального результата.
            history_property: Свойство для истории итераций. Default ``"reflection_history"``.
            timeout_s: Таймаут на один LLM-вызов. Default ``300``.

        Example::

            builder.reflection_loop_workflow(
                generator_workflow_id="generate_draft",
                reflector_workflow_id="reflect",
                refiner_workflow_id="refine",
                max_iterations=3,
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.reflection_loop import (
            ReflectionLoopProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ReflectionLoopProcessor(
                generator_workflow_id=generator_workflow_id,
                reflector_workflow_id=reflector_workflow_id,
                refiner_workflow_id=refiner_workflow_id,
                max_iterations=max_iterations,
                stop_verdict=stop_verdict,
                result_property=result_property,
                history_property=history_property,
                timeout_s=timeout_s,
            )
        )



    def hitl_approval(
        self,
        *,
        task: str,
        approvers: list[str] | None = None,
        timeout_seconds: float = 3600.0,
        result_property: str = "hitl.decision",
        priority: str = "normal",
    ) -> RouteBuilder:
        """Human-In-The-Loop approval с timeout и multi-approver support (S28 W5).

        Приостанавливает текущий pipeline, создаёт запрос на approval
        и ожидает ответа от человека. Результат записывается в
        ``result_property`` как dict с полями ``status``, ``approved_by``, ``reason``.

        Args:
            task: Описание задачи для approver'а.
            approvers: Список email или ID approvers.
            timeout_seconds: Timeout ожидания (default 3600).
            result_property: Exchange property для записи результата.
            priority: Приоритет (``critical``, ``high``, ``normal``, ``low``).

        Example::

            builder.hitl_approval(
                task="Подтвердите перевод 50000 RUB на счёт получателя",
                approvers=["manager@bank.ru"],
                timeout_seconds=3600,
            )
        """
        from src.backend.dsl.engine.processors.hitl_approval import (
            HitlApprovalProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            HitlApprovalProcessor(
                task=task,
                approvers=approvers,
                timeout_seconds=timeout_seconds,
                result_property=result_property,
                priority=priority,
            )
        )

