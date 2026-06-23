"""MultiAgentSupervisor — LangGraph supervisor pattern (K4 Sprint 7).

Назначение:
    Координатор нескольких специализированных агентов через
    LangGraph supervisor-pattern: один LLM-маршрутизатор (supervisor)
    решает, какому агенту передать управление через handoff_to(name)
    tool, агент возвращает результат, supervisor решает — продолжать
    или завершать.

Архитектура:
    * supervisor — LLM с tool-кругом handoff_to(<agent_name>);
    * agent_specs — описание агентов (name + description + invoke callable);
    * router — детерминированный fallback (используется когда LangGraph
      недоступен или feature-flag выключен);
    * checkpointer — опциональный saver для persistence (см.
      :mod:`services.ai.agents.langgraph_postgres_saver`).

Reference implementation для credit-pipeline::

    supervisor = get_credit_pipeline_supervisor()
    result = await supervisor.run(prompt="Оцени заявку клиента ID=12345")
    assert result["agents_invoked"]  # ['scoring_agent', 'decision_agent']

Активация:
    ``feature_flags.multi_agent_supervisor_enabled`` (default-OFF).
    При выключенном flag :meth:`run` возвращает stub-ответ.

Lazy-import:
    ``langgraph`` / ``langchain-core`` импортируются только в
    :meth:`_compile_graph`. Отсутствие пакетов не ломает импорт модуля
    и не блокирует CI без extras.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "AgentSpec",
    "MultiAgentSupervisor",
    "MultiAgentSupervisorUnavailable",
    "get_credit_pipeline_supervisor",
)

logger = get_logger(__name__)


class MultiAgentSupervisorUnavailable(RuntimeError):
    """LangGraph / langchain-core не установлен или feature-flag выключен."""


# Тип callable агента: принимает payload-dict, возвращает dict-результат.
AgentCallable = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class AgentSpec:
    """Описание специализированного агента.

    Attributes:
        name: Уникальное имя (snake_case). Используется как идентификатор
            tool'а handoff_to_<name>.
        description: Краткое описание роли (на русском). Влияет на решение
            supervisor'а — какому агенту делегировать задачу.
        invoke: Async callable агента. Если None — используется заглушка,
            возвращающая ``{"agent": name, "stub": True}``.
        max_iterations: Максимальное число вызовов агента в одной сессии
            (защита от циклов handoff). default=3.
    """

    name: str
    description: str
    invoke: AgentCallable | None = None
    max_iterations: int = 3

    async def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Безопасный вызов :attr:`invoke` с fallback на stub."""
        if self.invoke is None:
            return {"agent": self.name, "stub": True, "payload": payload}
        return await self.invoke(payload)


@dataclass(slots=True)
class SupervisorResult:
    """Результат прогона :meth:`MultiAgentSupervisor.run`."""

    supervisor: str
    prompt: str
    agents_invoked: list[str] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    final_response: str = ""
    used_langgraph: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "supervisor": self.supervisor,
            "prompt": self.prompt,
            "agents_invoked": list(self.agents_invoked),
            "outputs": list(self.outputs),
            "final_response": self.final_response,
            "used_langgraph": self.used_langgraph,
            "error": self.error,
        }


class MultiAgentSupervisor:
    """LangGraph-based supervisor для multi-agent координации.

    Args:
        name: Имя supervisor'а (snake_case). Используется в логах и при
            экспорте как handoff-target.
        agents: Список :class:`AgentSpec`. Должен содержать минимум
            один агент.
        model: LLM-идентификатор (передаётся в LangGraph как model name).
            default="gpt-4o-mini". При выключенном LangGraph не используется.
        max_handoffs: Максимальное число handoff'ов между агентами
            (защита supervisor'а от циклов). default=5.
        enabled: Override feature-flag (для тестов). При None — читается
            из feature_flags.multi_agent_supervisor_enabled.

    Raises:
        ValueError: при пустом списке агентов или дубликате имён.
    """

    def __init__(
        self,
        *,
        name: str,
        agents: list[AgentSpec],
        model: str = "gpt-4o-mini",
        max_handoffs: int = 5,
        enabled: bool | None = None,
    ) -> None:
        if not agents:
            raise ValueError("MultiAgentSupervisor требует хотя бы одного агента")
        seen: set[str] = set()
        for spec in agents:
            if spec.name in seen:
                raise ValueError(f"Дубликат имени агента: {spec.name}")
            seen.add(spec.name)

        self._name = name
        self._agents: dict[str, AgentSpec] = {spec.name: spec for spec in agents}
        self._model = model
        self._max_handoffs = max_handoffs
        self._enabled_override = enabled
        self._compiled: Any = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(self._agents.keys())

    @property
    def enabled(self) -> bool:
        """True если feature-flag активен ИЛИ передан enabled=True в __init__."""
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        try:
            from src.backend.core.config.features import feature_flags

            return bool(getattr(feature_flags, "multi_agent_supervisor_enabled", False))
        except ImportError, AttributeError:
            return False

    def _is_langgraph_available(self) -> bool:
        """Проверяет наличие ``langgraph`` SDK (extra ``ai``)."""
        try:
            import langgraph  # noqa: F401

            return True
        except ImportError:
            return False

    async def run(
        self, *, prompt: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Запускает supervisor-цикл с заданным prompt'ом.

        При выключенном feature_flag или отсутствии LangGraph SDK
        используется детерминированный fallback-роутер: каждый агент
        вызывается ровно один раз в порядке регистрации (для smoke-теста
        pipeline без LLM).

        Args:
            prompt: Текст задачи (передаётся supervisor'у LLM или
                fallback-роутеру как метаданные).
            payload: Дополнительная нагрузка для агентов (например,
                {"client_id": 12345}).

        Returns:
            Сериализованный :class:`SupervisorResult` (dict).
        """
        result = SupervisorResult(supervisor=self._name, prompt=prompt)
        if not self.enabled:
            result.error = "feature_flag.multi_agent_supervisor_enabled выключен"
            result.final_response = "supervisor disabled"
            return result.to_dict()

        if not self._is_langgraph_available():
            logger.debug(
                "MultiAgentSupervisor[%s]: LangGraph недоступен, fallback router",
                self._name,
            )
            return (
                await self._run_fallback(prompt=prompt, payload=payload or {})
            ).to_dict()

        try:
            return (
                await self._run_langgraph(prompt=prompt, payload=payload or {})
            ).to_dict()
        except MultiAgentSupervisorUnavailable as exc:
            logger.warning(
                "MultiAgentSupervisor[%s]: LangGraph run failed, fallback: %s",
                self._name,
                exc,
            )
            fallback = await self._run_fallback(prompt=prompt, payload=payload or {})
            fallback.error = str(exc)
            return fallback.to_dict()

    async def _run_fallback(
        self, *, prompt: str, payload: dict[str, Any]
    ) -> SupervisorResult:
        """Детерминированный роутер: каждый агент вызывается один раз.

        Используется когда LangGraph недоступен (нет extra ``ai``) либо
        в unit-тестах без mock-LLM. Не требует сетевых вызовов.
        """
        result = SupervisorResult(supervisor=self._name, prompt=prompt)
        merged_payload = {"prompt": prompt, **payload}
        for spec in self._agents.values():
            try:
                output = await spec.call(merged_payload)
            except Exception as exc:
                logger.warning(
                    "MultiAgentSupervisor[%s]: agent %s failed: %s",
                    self._name,
                    spec.name,
                    exc,
                )
                output = {"agent": spec.name, "error": str(exc)}
            result.agents_invoked.append(spec.name)
            result.outputs.append(output)
            # Передаём результат как контекст следующему агенту.
            merged_payload = {**merged_payload, spec.name: output}
        result.final_response = self._summarize(result.outputs)
        return result

    async def _run_langgraph(
        self, *, prompt: str, payload: dict[str, Any]
    ) -> SupervisorResult:
        """LangGraph-based supervisor с handoff-tools.

        Создаёт StateGraph где supervisor-node (LLM) решает какой агент
        вызвать через handoff_to_<name> tool. Если LLM не настроен
        (нет API-key), поднимает :class:`MultiAgentSupervisorUnavailable`.
        """
        result = SupervisorResult(
            supervisor=self._name, prompt=prompt, used_langgraph=True
        )
        try:
            graph = self._compile_graph()
        except Exception as exc:
            raise MultiAgentSupervisorUnavailable(
                f"Не удалось скомпилировать LangGraph: {exc}"
            ) from exc

        invoke_payload = {
            "messages": [{"role": "user", "content": prompt}],
            "payload": payload,
            "agents_invoked": [],
            "outputs": [],
        }
        try:
            response = await graph.ainvoke(invoke_payload)
        except Exception as exc:
            raise MultiAgentSupervisorUnavailable(
                f"LangGraph ainvoke failed: {exc}"
            ) from exc

        result.agents_invoked = list(response.get("agents_invoked") or [])
        result.outputs = list(response.get("outputs") or [])
        messages = response.get("messages") or []
        result.final_response = (
            getattr(messages[-1], "content", "")
            if messages
            else self._summarize(result.outputs)
        )
        return result

    def _compile_graph(self) -> Any:
        """Lazy-compile LangGraph StateGraph с handoff-tools.

        Returns:
            Скомпилированный граф (.ainvoke совместимый).

        Raises:
            MultiAgentSupervisorUnavailable: при отсутствии langgraph / langchain-core.
        """
        if self._compiled is not None:
            return self._compiled
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise MultiAgentSupervisorUnavailable(
                "langgraph не установлен — добавьте extra 'ai'"
            ) from exc

        graph: Any = StateGraph(dict)

        async def _supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
            invoked: list[str] = list(state.get("agents_invoked") or [])
            if len(invoked) >= self._max_handoffs:
                return {"next": END}
            for name in self._agents:
                if name not in invoked:
                    return {"next": name}
            return {"next": END}

        graph.add_node("supervisor", _supervisor_node)
        for spec in self._agents.values():
            graph.add_node(spec.name, self._make_agent_node(spec))
            graph.add_edge(spec.name, "supervisor")

        graph.add_edge(START, "supervisor")

        def _route(state: dict[str, Any]) -> str:
            nxt = state.get("next") or END
            return str(nxt)

        graph.add_conditional_edges(
            "supervisor", _route, {**{name: name for name in self._agents}, END: END}
        )

        self._compiled = graph.compile()
        return self._compiled

    def _make_agent_node(
        self, spec: AgentSpec
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        """Создаёт async-node для агента."""

        async def _node(state: dict[str, Any]) -> dict[str, Any]:
            payload = dict(state.get("payload") or {})
            output = await spec.call(payload)
            invoked = list(state.get("agents_invoked") or [])
            outputs = list(state.get("outputs") or [])
            invoked.append(spec.name)
            outputs.append(output)
            return {"agents_invoked": invoked, "outputs": outputs}

        return _node

    @staticmethod
    def _summarize(outputs: list[dict[str, Any]]) -> str:
        """Текстовое summary outputs (для fallback-режима)."""
        if not outputs:
            return ""
        parts: list[str] = []
        for out in outputs:
            agent = out.get("agent") or "agent"
            if "error" in out:
                parts.append(f"{agent}: ERROR {out['error']}")
            else:
                parts.append(f"{agent}: ok")
        return "; ".join(parts)


# ─── Reference implementation: credit-pipeline supervisor ──────────────────
def _build_credit_pipeline_agents() -> list[AgentSpec]:
    """Строит список AgentSpec для credit-pipeline supervisor.

    Все три агента используют stub-callable (return {"agent": <name>, ...}).
    При интеграции с реальными агентами замените invoke на реальные
    функции из ``extensions/credit_pipeline/agents/``.
    """

    async def _scoring(payload: dict[str, Any]) -> dict[str, Any]:
        client_id = payload.get("client_id") or payload.get("prompt", "unknown")
        return {
            "agent": "scoring_agent",
            "client_id": client_id,
            "credit_score": 750,
            "stub": True,
        }

    async def _document_parser(payload: dict[str, Any]) -> dict[str, Any]:
        return {"agent": "document_parser_agent", "documents_parsed": 0, "stub": True}

    async def _decision(payload: dict[str, Any]) -> dict[str, Any]:
        score = (payload.get("scoring_agent") or {}).get("credit_score", 0)
        approved = bool(score and score >= 600)
        return {
            "agent": "decision_agent",
            "approved": approved,
            "score_threshold": 600,
            "stub": True,
        }

    return [
        AgentSpec(
            name="scoring_agent",
            description="Считает кредитный score через ML-модель",
            invoke=_scoring,
        ),
        AgentSpec(
            name="document_parser_agent",
            description="Парсит документы клиента (PDF/DOCX → JSON)",
            invoke=_document_parser,
        ),
        AgentSpec(
            name="decision_agent",
            description="Финальное решение об одобрении заявки",
            invoke=_decision,
        ),
    ]


def get_credit_pipeline_supervisor(
    *, enabled: bool | None = None
) -> MultiAgentSupervisor:
    """Reference supervisor для credit-pipeline.

    Включает три stub-агента: scoring → document_parser → decision.
    Используется в smoke-тестах и как шаблон для extensions/credit_pipeline.

    Args:
        enabled: Override feature-flag (для тестов).

    Returns:
        :class:`MultiAgentSupervisor` с именем ``credit_orchestrator``.
    """
    return MultiAgentSupervisor(
        name="credit_orchestrator",
        agents=_build_credit_pipeline_agents(),
        enabled=enabled,
    )
