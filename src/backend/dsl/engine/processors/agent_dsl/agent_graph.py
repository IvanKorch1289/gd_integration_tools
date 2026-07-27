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

Security:
    Pre-flight AgentToolPolicy gate (M2.1): перед вызовом ``sandbox.run_react``
    processors фильтрует ``tool_actions`` через зарегистрированный
    :class:`AgentToolPolicy` из DI. Если после фильтрации список пуст — sandbox
    НЕ вызывается, возвращается ``{"error": "all tools denied by AgentToolPolicy",
    "graph_type": "react"}`` (early-error). Defensive default: если policy
    не зарегистрирована — ``tool_actions`` пропускаются без фильтрации
    (backwards-compatible).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.ai.agent_sandbox_protocol import AgentSandbox
from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AgentGraphProcessor",)

_logger = get_logger(__name__)


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
        sandbox: AgentSandbox | None = None,
        isolated: bool = True,  # Cycle 30 P0-#6: ProcessPool default (was False)
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
        self._isolated = isolated
        # S3 fix follow-up (S36-W15): explicit sandbox honoring ``isolated`` flag.
        # До этого fix line 148: ``sandbox or InProcessAgentSandbox()`` —
        # default-нулевая изоляция игнорировала ``isolated=True`` builder flag.
        # Семантика: caller-инжектированный ``sandbox`` имеет приоритет; иначе
        # ProcessPool при isolated=True (default с S3) / InProcess при isolated=False.
        if sandbox is not None:
            self._sandbox = sandbox
        elif isolated:
            from src.backend.services.ai.agent_sandbox import (
                get_process_pool_agent_sandbox,
            )

            self._sandbox = get_process_pool_agent_sandbox()
        else:
            # Явный opt-in в zero-isolation: warning + audit event в _run.
            from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

            self._sandbox = InProcessAgentSandbox()

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope = first workflow_id for capability gate."""
        if self.agents:
            return self.agents[0].get("workflow_id")
        return None

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self.graph_type == "supervisor":
            result = await self._run_supervisor(exchange, context)
        else:
            result = await self._run_react(exchange, context)

        exchange.set_property(self.result_property, result)

    async def _run_supervisor(
        self, exchange: Exchange[Any], context: ExecutionContext
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
        return await supervisor.run(
            prompt=prompt, payload=self._build_payload(exchange)
        )

    async def _run_react(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> dict[str, Any]:
        """Execute ReAct agent via configured sandbox."""
        # Pre-flight AgentToolPolicy gate (M2.1): если все tools зафильтрованы
        # по policy — не вызываем sandbox, возвращаем early-error.
        filtered_tools = self._filter_tools_by_policy(self.tool_actions)
        if not filtered_tools:
            return {
                "error": "all tools denied by AgentToolPolicy",
                "graph_type": "react",
            }
        prompt = self._prompt_with_context(exchange)
        result = await self._sandbox.run_react(
            prompt=prompt,
            tool_actions=filtered_tools,
            model=self.model,
            temperature=0.0,
            durable=False,
            session_id=exchange.meta.correlation_id,
        )
        if result.success:
            return result.data
        return {"error": result.data.get("error", "unknown"), "graph_type": "react"}

    def _filter_tools_by_policy(
        self, tool_actions: list[str]
    ) -> list[str]:
        """Filter tool_actions через AgentToolPolicy (S170 P0-7, M2.1).

        Fail-closed: если policy недоступна/не зарегистрирована/падает —
        возвращаем пустой список (запрет ВСЕХ tools). Это безопаснее
        fail-open, который пропускал все tools при сбое policy-check.

        ponytail: trade-off fail-closed — extensions с неполным DI рискуют
        потерять tool actions. Альтернатива — explicit fallback opt-in
        через env `AGENT_TOOL_POLICY_FAIL_OPEN=true` (см. ниже).

        Returns:
            Список tools, для которых ``policy.check(tool) == "allow"``.
        """
        import os
        fail_open_env = os.environ.get("AGENT_TOOL_POLICY_FAIL_OPEN", "").lower() in (
            "1", "true", "yes"
        )

        try:
            from src.backend.ai.policy import AgentToolPolicy
            from src.backend.core.svcs_registry import get_service, has_service
        except ImportError:
            _logger.warning(
                "agent_graph tool_policy: AgentToolPolicy import failed; "
                "blocking all tools (fail-closed)"
            )
            return [] if not fail_open_env else list(tool_actions)

        try:
            if not has_service(AgentToolPolicy):
                _logger.warning(
                    "agent_graph tool_policy: AgentToolPolicy not registered in DI; "
                    "blocking all tools (fail-closed)"
                )
                return [] if not fail_open_env else list(tool_actions)
            policy = get_service(AgentToolPolicy)
        except Exception:
            _logger.warning(
                "agent_graph tool_policy: failed to resolve AgentToolPolicy from DI; "
                "blocking all tools (fail-closed)",
                exc_info=True,
            )
            return [] if not fail_open_env else list(tool_actions)

        allowed: list[str] = []
        for tool in tool_actions:
            try:
                if policy.is_allowed(tool):
                    allowed.append(tool)
            except Exception:
                continue
        return allowed

    # Cycle 4 swarm (AI-5): cap prompt length to prevent prompt-injection
    # abuse via oversized or attacker-controlled exchange body values.
    _MAX_PROMPT_LEN = 4000

    def _extract_prompt(self, exchange: Exchange[Any]) -> str:
        """Extract prompt from exchange body or property.

        Cycle 4 hardening: cap at _MAX_PROMPT_LEN chars.
        """
        body = exchange.in_message.body
        prompt: str | None = None
        if isinstance(body, dict):
            for key in ("prompt", "content"):
                val = body.get(key)
                if isinstance(val, str) and val:
                    prompt = val
                    break
        if prompt is None:
            if isinstance(body, str):
                prompt = body
            else:
                prompt = str(body or "")
        if len(prompt) > self._MAX_PROMPT_LEN:
            import logging
            logging.getLogger(__name__).warning(
                "%s: prompt truncated from %d to %d chars (S227 cycle 4 hardening)",
                self.name, len(prompt), self._MAX_PROMPT_LEN,
            )
            prompt = prompt[: self._MAX_PROMPT_LEN]
        return prompt

    def _prompt_with_context(self, exchange: Exchange[Any]) -> str:
        """Build prompt with exchange context for ReAct agent.

        Cycle 4 hardening: cap total prompt at _MAX_PROMPT_LEN.
        """
        prompt = self.prompt_inline or ""
        body = exchange.in_message.body
        if isinstance(body, dict):
            user_input = (
                body.get("user_input") or body.get("query") or body.get("prompt")
            )
            if user_input:
                prompt = f"{prompt}\n\nContext: {user_input}"
        if len(prompt) > self._MAX_PROMPT_LEN:
            import logging
            logging.getLogger(__name__).warning(
                "%s: composed prompt truncated from %d to %d chars (S227 cycle 4 hardening)",
                self.name, len(prompt), self._MAX_PROMPT_LEN,
            )
            prompt = prompt[: self._MAX_PROMPT_LEN]
        return prompt

    def _build_payload(self, exchange: Exchange[Any]) -> dict[str, Any]:
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
        if self._isolated:
            spec["isolated"] = True
        return {"agent_graph": spec}
