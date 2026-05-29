"""OrchestratorEngine — runtime маршрутизация задач между агентами (S28 W4).

План Agent DSL + Memory Orchestration Layer, Phase 4.

-engine выполняет routing task → agent на основе :class:`OrchestratorSpec`
и :class:`RoutingRule` с JMESPath evaluation.

Feature-flag: :envvar:`FEATURE_WORKFLOW_ORCHESTRATOR_ENABLED` (default-OFF).

Usage::

    engine = OrchestratorEngine(registry=agent_registry)
    result = await engine.route(
        task={"input": {"type": "score", "body": {...}}},
        orchestrator_spec=orchestrator_spec,
    )
    # result.target_agent, result.target_model, result.memory_scope

См. также
---------
* :class:`OrchestratorSpec` — :mod:`dsl.workflow.orchestrator`.
* :class:`AgentRegistry` — :mod:`core.ai.agent_registry`.
* :class:`AgentSpec` — :mod:`core.ai.agent_spec`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.ai.agent_registry import AgentRegistry
    from src.backend.core.ai.agent_spec import AgentSpec
    from src.backend.dsl.workflow.orchestrator import OrchestratorSpec

__all__ = ("OrchestratorEngine", "RoutingResult")

logger = logging.getLogger("workflow.orchestrator")


@dataclass(frozen=True, slots=True)
class RoutingResult:
    """Результат маршрутизации задачи к агенту.

    Attributes:
        target_agent: AgentSpec выбранного агента.
        target_model: Модель для использования (может быть переопределена
            в routing rule).
        memory_scope: Memory scope для этого вызова (из rule или agent).
        matched_rule: Индекс matched routing rule (для audit).
    """

    target_agent: "AgentSpec"
    target_model: str
    memory_scope: Any = None
    matched_rule: int | None = None


class OrchestratorEngine:
    """Engine маршрутизации задач между агентами (S28 W4).

    Использует JMESPath для evaluate ``RoutingRule.when`` условий
    относительно task input.

    DI: передаётся ``AgentRegistry`` через конструктор.
    Feature-flag ``workflow_orchestrator_enabled`` проверяется в
    :meth:`route` (при ``False`` возвращает ``default_agent``).
    """

    def __init__(self, *, registry: "AgentRegistry") -> None:
        """Инициализация engine.

        Args:
            registry: Ссылка на :class:`AgentRegistry` для lookup агентов.
        """
        self._registry = registry

    async def route(
        self, task: dict[str, Any], orchestrator_spec: "OrchestratorSpec"
    ) -> RoutingResult:
        """Маршрутизировать задачу к агенту на основе routing rules.

        Evaluates JMESPath conditions из ``orchestrator_spec.routing``
        по порядку. Первое matching rule применяется.

        Args:
            task: Словарь task input ( например
                ``{"input": {"type": "score", "body": {...}}}``).
            orchestrator_spec: Orchestrator specification.

        Returns:
            :class:`RoutingResult` с target agent, model и memory scope.

        Raises:
            KeyError: Агент не найден в registry.
            ValueError: Ни одно правило не сработало и ``default_agent``
                не задан.
        """
        # Feature-flag check (default-OFF)
        if not self._is_orchestrator_enabled():
            # Fallback: return default_agent if available
            if orchestrator_spec.default_agent:
                agent = self._registry.get_agent(orchestrator_spec.default_agent)
                return RoutingResult(target_agent=agent, target_model=agent.model)
            raise ValueError(
                "OrchestratorEngine.route: workflow_orchestrator_enabled=False "
                "and no default_agent specified"
            )

        # Evaluate routing rules
        for idx, rule in enumerate(orchestrator_spec.routing):
            if self._evaluate_condition(rule.when, task):
                agent_id = rule.use_agent or orchestrator_spec.default_agent
                if agent_id is None:
                    raise ValueError(
                        f"Routing rule[{idx}] matched but use_agent and "
                        "default_agent are both None"
                    )
                agent = self._registry.get_agent(agent_id)
                model = rule.use_model or agent.model
                memory_scope = rule.memory_scope or agent.memory
                logger.debug(
                    "OrchestratorEngine: rule[%d] matched, routing to agent=%s",
                    idx,
                    agent_id,
                )
                return RoutingResult(
                    target_agent=agent,
                    target_model=model,
                    memory_scope=memory_scope,
                    matched_rule=idx,
                )

        # No rule matched — use default_agent
        if orchestrator_spec.default_agent:
            agent = self._registry.get_agent(orchestrator_spec.default_agent)
            return RoutingResult(target_agent=agent, target_model=agent.model)

        raise ValueError(
            "OrchestratorEngine.route: no routing rule matched and "
            "default_agent is not set"
        )

    # ── Internal helpers ────────────────────────────────────────────

    def _is_orchestrator_enabled(self) -> bool:
        """Проверить feature-flag workflow_orchestrator_enabled.

        Returns:
            True если enabled, False если disabled (default-OFF).
        """
        try:
            from src.backend.core.config.features import FeatureFlags

            return getattr(FeatureFlags, "workflow_orchestrator_enabled", False)
        except ImportError:
            return False

    def _evaluate_condition(self, jmespath_expr: str, task: dict[str, Any]) -> bool:
        """Вычислить JMESPath condition относительно task input.

        Args:
            jmespath_expr: JMESPath выражение (например ``"input.type == 'score'"``).
            task: Task dictionary для evaluation context.

        Returns:
            True если результат truthy, False otherwise.
        """
        try:
            import jmespath

            # Navigate to input field (task is {"input": {...}})
            data = task.get("input", task)
            result = jmespath.search(jmespath_expr, data)
            return bool(result)
        except Exception as exc:
            logger.warning(
                "OrchestratorEngine: JMESPath evaluation failed for %r: %s",
                jmespath_expr,
                exc,
            )
            return False
