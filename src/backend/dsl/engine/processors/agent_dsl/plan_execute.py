"""PlanExecuteProcessor — Plan-and-Execute agentic pattern (S39 W2).

ReAct-альтернатива для сложных многошаговых задач:
1. **Plan** — LLM генерирует структурированный план (список шагов).
2. **Execute** — каждый шаг выполняется через отдельный LLM-вызов.
3. **Verify** — результат шага верифицируется; при ``fail`` — replan.

YAML контракт::

    steps:
      - plan_execute:
          planner_workflow_id: "generate_plan"
          executor_workflow_id: "execute_step"
          verifier_workflow_id: "verify_step"
          max_replans: 3
          plan_output_property: "plan"
          result_property: "plan_execute_result"

Python контракт через :meth:`AgentDSLMixin.plan_execute`::

    builder.plan_execute(
        planner_workflow_id="generate_plan",
        executor_workflow_id="execute_step",
        verifier_workflow_id="verify_step",
        max_replans=3,
    )
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor
from src.backend.services.ai.gateway.exceptions import GatewayUnavailable

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("PlanExecuteProcessor",)

_logger = get_logger(__name__)


class PlanExecuteProcessor(BaseAIProcessor):
    """Plan → Execute → Verify с автоматическим replan.

    Args:
        planner_workflow_id: workflow_id для LLM, генерирующего план.
        executor_workflow_id: workflow_id для LLM, выполняющего шаг.
        verifier_workflow_id: workflow_id для LLM, верифицирующего результат.
        max_replans: Максимальное число попыток перепланировать.
        plan_output_property: Свойство, куда сохранить сгенерированный план.
        result_property: Свойство, куда сохранить финальный результат.
        timeout_s: Таймаут на один LLM-вызов.
        name: Имя процессора.
    """

    required_capability: ClassVar[str | None] = "ai.invoke"
    audit_event: ClassVar[str | None] = "ai.agent.plan_execute"

    def __init__(
        self,
        *,
        planner_workflow_id: str,
        executor_workflow_id: str,
        verifier_workflow_id: str,
        max_replans: int = 3,
        plan_output_property: str = "plan",
        result_property: str = "plan_execute_result",
        timeout_s: float = 300.0,
        name: str | None = None,
    ) -> None:
        if not planner_workflow_id:
            raise ValueError("PlanExecuteProcessor: planner_workflow_id обязателен")
        if not executor_workflow_id:
            raise ValueError("PlanExecuteProcessor: executor_workflow_id обязателен")
        if not verifier_workflow_id:
            raise ValueError("PlanExecuteProcessor: verifier_workflow_id обязателен")
        super().__init__(name=name or f"plan_execute:{planner_workflow_id}")
        self.planner_workflow_id = planner_workflow_id
        self.executor_workflow_id = executor_workflow_id
        self.verifier_workflow_id = verifier_workflow_id
        self.max_replans = max_replans
        self.plan_output_property = plan_output_property
        self.result_property = result_property
        self.timeout_s = timeout_s

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        _ = context  # Зарезервировано для майбутнього use (correlation, tenant_id)
        gateway = self._resolve_gateway()
        if gateway is None:
            exchange.set_error(
                f"{self.name}: AIGateway не найден в DI — нельзя выполнить plan_execute"
            )
            exchange.stop()
            return

        replan_count = 0
        plan: list[dict[str, Any]] | None = None
        previous_errors: list[str] = []

        while replan_count <= self.max_replans:
            # ── 1. Plan ──
            plan = await self._generate_plan(gateway, exchange, previous_errors)
            if plan is None:
                exchange.set_error(f"{self.name}: не удалось сгенерировать план")
                exchange.stop()
                return

            exchange.set_property(self.plan_output_property, plan)
            _logger.debug("%s: plan generated (%d steps)", self.name, len(plan))

            # ── 2. Execute + Verify ──
            all_passed = True
            step_results: list[dict[str, Any]] = []

            for idx, step in enumerate(plan):
                step_id = step.get("id", str(idx + 1))
                step_description = step.get("description", "")

                # Execute
                exec_result = await self._execute_step(
                    gateway, exchange, step_id, step_description, step
                )
                if exec_result is None:
                    exchange.set_error(f"{self.name}: step {step_id} execution failed")
                    exchange.stop()
                    return

                # Verify
                verify_result = await self._verify_step(
                    gateway, exchange, step_id, step_description, exec_result
                )
                if verify_result is None:
                    exchange.set_error(
                        f"{self.name}: step {step_id} verification failed"
                    )
                    exchange.stop()
                    return

                verdict = verify_result.get("verdict", "fail")
                if verdict != "ok":
                    all_passed = False
                    error_msg = verify_result.get(
                        "reason", f"step {step_id} verification failed"
                    )
                    previous_errors.append(error_msg)
                    _logger.info(
                        "%s: step %s failed verification (%s), replan %d/%d",
                        self.name,
                        step_id,
                        error_msg,
                        replan_count + 1,
                        self.max_replans,
                    )
                    break

                step_results.append(
                    {
                        "step_id": step_id,
                        "description": step_description,
                        "result": exec_result.get("output", ""),
                        "verdict": verdict,
                    }
                )

            if all_passed:
                exchange.set_property(
                    self.result_property,
                    {
                        "status": "success",
                        "plan": plan,
                        "step_results": step_results,
                        "replan_count": replan_count,
                    },
                )
                return

            replan_count += 1

        # Исчерпаны replan-attempts
        exchange.set_error(
            f"{self.name}: исчерпаны попытки replan ({self.max_replans})"
        )
        exchange.stop()

    # ── internal helpers ──

    async def _generate_plan(
        self, gateway: Any, exchange: Exchange[Any], previous_errors: list[str]
    ) -> list[dict[str, Any]] | None:
        """Вызвать planner_workflow_id и распарсить JSON-план."""
        context = self._build_context(exchange, previous_errors)
        response = await self._call_workflow(gateway, self.planner_workflow_id, context)
        if response is None:
            return None
        return self._parse_plan(response)

    async def _execute_step(
        self,
        gateway: Any,
        exchange: Exchange[Any],
        step_id: str,
        step_description: str,
        step: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Вызвать executor_workflow_id для конкретного шага."""
        context = {
            **self._build_context(exchange),
            "step_id": step_id,
            "step_description": step_description,
            "step_input": step.get("input", {}),
        }
        response = await self._call_workflow(
            gateway, self.executor_workflow_id, context
        )
        if response is None:
            return None
        return {
            "output": getattr(response, "content", ""),
            "structured": getattr(response, "structured", None),
        }

    async def _verify_step(
        self,
        gateway: Any,
        exchange: Exchange[Any],
        step_id: str,
        step_description: str,
        exec_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Вызвать verifier_workflow_id и вернуть verdict dict."""
        context = {
            **self._build_context(exchange),
            "step_id": step_id,
            "step_description": step_description,
            "step_output": exec_result.get("output", ""),
            "step_structured": exec_result.get("structured"),
        }
        response = await self._call_workflow(
            gateway, self.verifier_workflow_id, context
        )
        if response is None:
            return None
        structured = getattr(response, "structured", None)
        if isinstance(structured, dict):
            return structured
        # fallback: парсим content как JSON
        content = getattr(response, "content", "")
        try:
            return json.loads(content) if content else {"verdict": "fail"}
        except json.JSONDecodeError:
            _logger.warning("%s: verifier returned non-JSON: %r", self.name, content)
            return {"verdict": "ok" if "ok" in content.lower() else "fail"}

    async def _call_workflow(
        self, gateway: Any, workflow_id: str, context: dict[str, Any]
    ) -> Any | None:
        """Один LLM-вызов через AIGateway."""
        from src.backend.core.ai.gateway import AIRequest

        request = AIRequest(
            workflow_id=workflow_id,
            tenant_id="unknown",
            correlation_id="plan-exec",
            prompt_inline=f"Context: {json.dumps(context, ensure_ascii=False)}",
        )
        try:
            return await gateway.invoke(request)
        except (GatewayUnavailable, OSError, TimeoutError) as exc:
            _logger.warning("%s: gateway.invoke failed: %s", self.name, exc)
            return None
        except Exception as exc:
            _logger.warning(
                "%s: gateway.invoke unexpected error: %s", self.name, exc, exc_info=True
            )
            return None

    @staticmethod
    def _build_context(
        exchange: Exchange[Any], previous_errors: list[str] | None = None
    ) -> dict[str, Any]:
        """Сформировать контекст для LLM из exchange."""
        ctx: dict[str, Any] = {
            "body": exchange.in_message.body
            if isinstance(exchange.in_message.body, dict)
            else {},
            "correlation_id": exchange.meta.correlation_id,
        }
        if previous_errors:
            ctx["previous_errors"] = previous_errors
        return ctx

    @staticmethod
    def _parse_plan(response: Any) -> list[dict[str, Any]] | None:
        """Извлечь список steps из AIResponse."""
        structured = getattr(response, "structured", None)
        if isinstance(structured, dict):
            steps = structured.get("steps")
            if isinstance(steps, list):
                return steps
        content = getattr(response, "content", "")
        if not content:
            return None
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                steps = parsed.get("steps")
                if isinstance(steps, list):
                    return steps
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            _logger.warning(
                "PlanExecuteProcessor: planner returned non-JSON plan: %r", content
            )
        return None

    @staticmethod
    def _resolve_gateway() -> Any | None:
        """Lazy-резолв AIGateway через DI."""
        try:
            from src.backend.services.ai.gateway_adapter import (  # type: ignore[attr-defined]
                get_ai_gateway,
            )

            return get_ai_gateway()
        except Exception:
            return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML DSL."""
        spec: dict[str, Any] = {
            "planner_workflow_id": self.planner_workflow_id,
            "executor_workflow_id": self.executor_workflow_id,
            "verifier_workflow_id": self.verifier_workflow_id,
        }
        if self.max_replans != 3:
            spec["max_replans"] = self.max_replans
        if self.plan_output_property != "plan":
            spec["plan_output_property"] = self.plan_output_property
        if self.result_property != "plan_execute_result":
            spec["result_property"] = self.result_property
        if self.timeout_s != 300.0:
            spec["timeout_s"] = self.timeout_s
        return {"plan_execute": spec}
