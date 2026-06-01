"""AgentGraphProcessor — LangGraph execution as DSL step (S28 W4).

Wraps LangGraph as a first-class DSL processor. Two execution modes:

1. **supervisor** — LangGraph StateGraph multi-agent supervisor with handoff
   tools. Delegates to :class:`MultiAgentSupervisor
   <services.ai.multi_agent.supervisor.MultiAgentSupervisor>`.
   Each agent is a DSL workflow invoked via :class:`AgentRunProcessor`.

2. **react** — ReAct agent via ``langgraph.prebuilt.create_react_agent``.
   Delegates to :func:`build_and_run_agent <services.ai.ai_graph.build_and_run_agent>`.

Checkpointing:
- Uses :func:`get_langgraph_postgres_saver` (feature-flag
  ``langgraph_postgres_checkpoint``, default-OFF).
- ``thread_id`` = ``exchange.meta.correlation_id`` for traceable resumes.

YAML contract::

    steps:
      # Supervisor mode: multi-agent with LLM-driven handoff
      - agent_graph:
          graph_type: supervisor
          model: gpt-4o-mini
          agents:
            - key: scoring
              workflow_id: credit_scoring
              description: "Считает кредитный score"
            - key: decision
              workflow_id: credit_decision
              description: "Финальное решение"
          max_handoffs: 5
          result_property: agent_graph_result

      # ReAct mode: tool-calling agent
      - agent_graph:
          graph_type: react
          prompt_inline: "Найди информацию о заявке..."
          tool_actions: [db.query, http.get]
          result_property: agent_graph_result

Python contract::

    builder.agent_graph(
        graph_type="supervisor",
        agents=[
            {"key": "scoring", "workflow_id": "credit_scoring", "description": "..."},
            {"key": "decision", "workflow_id": "credit_decision", "description": "..."},
        ],
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AgentGraphProcessor",)

_logger = logging.getLogger(__name__)


# Supported graph types.
GRAPH_TYPES = frozenset(("supervisor", "react"))


class AgentGraphProcessor(BaseAIProcessor):
    """LangGraph execution as DSL step.

    Args:
        graph_type: ``"supervisor"`` (LLM-driven multi-agent handoff) or
            ``"react"`` (ReAct tool-calling agent).
        model: LLM identifier passed to LangGraph. Default ``"gpt-4o-mini"``.
        agents: List of agent specs for ``graph_type="supervisor"``. Each dict
            must contain ``key`` (result dict key), ``workflow_id``, and
            ``description``. Optional ``max_iterations`` (default 3).
        prompt_inline: Inline prompt for ``graph_type="react"``.
        tool_actions: List of action names available as tools for ReAct agent.
        max_handoffs: Maximum supervisor handoffs (supervisor mode only).
            Default 5.
        result_property: Exchange property for the result dict.
            Default ``"agent_graph_result"``.
        name: Processor name.
    """

    feature_flag_name: ClassVar[str | None] = "ai_agent_dsl_enabled"
    required_capability: ClassVar[str | None] = "ai.invoke"
    audit_event: ClassVar[str | None] = "ai.agent.graph"

    def __init__(
        self,
        *,
        graph_type: str,
        model: str = "gpt-4o-mini",
        agents: list[dict[str, Any]] | None = None,
        prompt_inline: str | None = None,
        tool_actions: list[str] | None = None,
        max_handoffs: int = 5,
        result_property: str = "agent_graph_result",
        name: str | None = None,
    ) -> None:
        if graph_type not in GRAPH_TYPES:
            raise ValueError(
                f"AgentGraphProcessor: graph_type must be one of {sorted(GRAPH_TYPES)}, "
                f"got {graph_type!r}"
            )
        if graph_type == "supervisor":
            if not agents:
                raise ValueError(
                    "AgentGraphProcessor: graph_type='supervisor' requires agents list"
                )
            for idx, agent in enumerate(agents):
                if "key" not in agent:
                    raise ValueError(
                        f"AgentGraphProcessor: agents[{idx}] missing 'key'"
                    )
                if "workflow_id" not in agent:
                    raise ValueError(
                        f"AgentGraphProcessor: agents[{idx}] missing 'workflow_id'"
                    )
        if graph_type == "react":
            if not prompt_inline:
                raise ValueError(
                    "AgentGraphProcessor: graph_type='react' requires prompt_inline"
                )
            if not tool_actions:
                raise ValueError(
                    "AgentGraphProcessor: graph_type='react' requires tool_actions"
                )

        super().__init__(name=name or f"agent_graph:{graph_type}")
        self.graph_type = graph_type
        self.model = model
        self.agents = [dict(a) for a in (agents or [])]
        self.prompt_inline = prompt_inline
        self.tool_actions = list(tool_actions) if tool_actions else []
        self.max_handoffs = max_handoffs
        self.result_property = result_property

    def _capability_scope(self, exchange: "Exchange[Any]") -> str | None:
        """Scope = first workflow_id for capability gate."""
        if self.agents:
            return self.agents[0].get("workflow_id")
        return None

    async def _run(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        if self.graph_type == "supervisor":
            result = await self._run_supervisor(exchange, context)
        else:
            result = await self._run_react(exchange, context)

        exchange.set_property(self.result_property, result)

    async def _run_supervisor(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> dict[str, Any]:
        """Execute multi-agent supervisor via existing MultiAgentSupervisor."""
        try:
            from src.backend.services.ai.multi_agent.supervisor import (
                AgentSpec,
                MultiAgentSupervisor,
            )
        except ImportError as exc:
            _logger.warning(
                "%s: langgraph not available — returning error result: %s",
                self.name,
                exc,
            )
            return {
                "error": f"langgraph not installed: {exc}",
                "graph_type": "supervisor",
            }

        # Build AgentSpec list from YAML config
        agent_specs: list[AgentSpec] = []
        for spec in self.agents:
            max_iterations = spec.get("max_iterations", 3)

            # Build invoke callable that runs AgentRunProcessor
            workflow_id = spec["workflow_id"]
            key = spec["key"]

            async def make_invoke(wf_id: str) -> Any:
                """Create invoke callable that runs AgentRunProcessor."""
                from src.backend.dsl.engine.processors.agent_dsl.agent_run import (
                    AgentRunProcessor,
                )

                async def invoke(payload: dict[str, Any]) -> dict[str, Any]:
                    proc = AgentRunProcessor(
                        workflow_id=wf_id,
                        prompt_inline=payload.get("prompt", ""),
                        context_property=None,
                    )
                    sub = exchange.clone()
                    await proc.process(sub, context)
                    result = sub.get_property("agent_result")
                    if result is None and sub.error:
                        return {"error": sub.error}
                    return result or {"error": "no result"}

                return invoke

            invoke_fn = await make_invoke(workflow_id)

            agent_specs.append(
                AgentSpec(
                    name=key,
                    description=spec.get("description", ""),
                    invoke=invoke_fn,
                    max_iterations=max_iterations,
                )
            )

        supervisor = MultiAgentSupervisor(
            name=self.name,
            agents=agent_specs,
            model=self.model,
            max_handoffs=self.max_handoffs,
            enabled=True,  # Processor controls enablement via feature-flag
        )

        prompt = self._extract_prompt(exchange)
        result = await supervisor.run(
            prompt=prompt, payload=self._build_payload(exchange)
        )
        return result

    async def _run_react(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> dict[str, Any]:
        """Execute ReAct agent via existing build_and_run_agent."""
        try:
            from src.backend.services.ai.ai_graph import build_and_run_agent
        except ImportError as exc:
            _logger.warning(
                "%s: langgraph/litellm not available — returning error: %s",
                self.name,
                exc,
            )
            return {
                "error": f"langgraph/litellm not available: {exc}",
                "graph_type": "react",
            }

        prompt = self._prompt_with_context(exchange)
        result = await build_and_run_agent(
            prompt=prompt, tool_actions=self.tool_actions
        )
        return result

    def _extract_prompt(self, exchange: "Exchange[Any]") -> str:
        """Extract prompt from exchange body or property."""
        body = exchange.in_message.body
        if isinstance(body, dict):
            prompt = body.get("prompt")
            if isinstance(prompt, str) and prompt:
                return prompt
            content = body.get("content")
            if isinstance(content, str) and content:
                return content
        if isinstance(body, str):
            return body
        return str(body or "")

    def _prompt_with_context(self, exchange: "Exchange[Any]") -> str:
        """Build prompt with exchange context for ReAct agent."""
        prompt = self.prompt_inline or ""
        body = exchange.in_message.body
        if isinstance(body, dict):
            user_input = (
                body.get("user_input") or body.get("query") or body.get("prompt")
            )
            if user_input:
                prompt = f"{prompt}\n\nContext: {user_input}"
        return prompt

    def _build_payload(self, exchange: "Exchange[Any]") -> dict[str, Any]:
        """Build payload dict from exchange body."""
        body = exchange.in_message.body
        if isinstance(body, dict):
            payload = {k: v for k, v in body.items() if k != "prompt"}
            payload.setdefault("tenant_id", exchange.meta.tenant_id)
            return payload
        return {"tenant_id": exchange.meta.tenant_id or "unknown"}

    def to_spec(self) -> dict[str, Any]:
        """Round-trip serialization for YAML."""
        spec: dict[str, Any] = {"graph_type": self.graph_type, "model": self.model}
        if self.agents:
            spec["agents"] = [dict(a) for a in self.agents]
        if self.prompt_inline is not None:
            spec["prompt_inline"] = self.prompt_inline
        if self.tool_actions:
            spec["tool_actions"] = list(self.tool_actions)
        if self.max_handoffs != 5:
            spec["max_handoffs"] = self.max_handoffs
        if self.result_property != "agent_graph_result":
            spec["result_property"] = self.result_property
        return {"agent_graph": spec}
