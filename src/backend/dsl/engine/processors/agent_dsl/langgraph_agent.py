"""DSL processor ``langgraph_agent`` (Sprint 170 S170 — agent layer).

Thin wrapper над :func:`src.backend.services.ai.ai_graph.build_and_run_agent`
(LangGraph-backed ReAct-агент с tools).

Ponytail: 1-line DSL поверх существующей core-функции, без абстракций.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("LangGraphAgentProcessor",)
_logger = get_logger(__name__)


from src.backend.dsl.registry import processor  # D-AGENTS-P1-002 fix (cycle 27)


@processor(
    "langgraph_agent",
    namespace="core",
    capabilities=("ai.langgraph.invoke",),
    spec_schema={
        "type": "object",
        "properties": {"graph_id": {"type": "string"}, "state": {"type": "object"}},
        "required": ["graph_id"],
    },
    meta={"tier": 1, "category": "agent"},
)
class LangGraphAgentProcessor(BaseAIProcessor):
    """DSL-процессор ``langgraph_agent``.

    Wraps LangGraph ReAct-agent через :func:`services.ai.ai_graph.build_and_run_agent`.

    Args:
        query: Запрос агенту.
        to: Куда записать ``output`` агента (default ``"body.answer"``).
        thread_id: Optional thread-id (для checkpointing).
        max_iterations: Лимит LangGraph iterations (default 10).
        name: Имя процессора.

    Example:
        >>> p = LangGraphAgentProcessor(query="What is INN 7707083893?", thread_id="t1")

    """

    required_capability: ClassVar[str | None] = "agent.run"
    audit_event: ClassVar[str | None] = "ai.agent.run"

    def __init__(
        self,
        *,
        query: str,
        to: str = "body.answer",
        thread_id: str | None = None,
        max_iterations: int = 10,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"langgraph_agent:{query[:30]}")
        self.query = query
        self.target = to
        self.thread_id = thread_id
        self.max_iterations = max_iterations

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        # The canonical BaseProcessor gate is async and fail-closed.
        if not await self.auth_check(exchange, action="execute"):
            return

        # Cycle 4c swarm (AI-5 hardening): cap query length to prevent
        # prompt-injection abuse via oversized query.
        if self.query and len(self.query) > 4000:
            # Cycle 75: use module-level canonical logger.
            _logger.warning(
                "%s: query truncated from %d to 4000 chars (S227 cycle 4)",
                self.name,
                len(self.query),
            )
            self.query = self.query[:4000]

        from src.backend.services.ai.ai_graph import build_and_run_agent

        result = await build_and_run_agent(
            query=self.query,
            thread_id=self.thread_id,
            max_iterations=self.max_iterations,
        )
        output = result.get("output", "") if isinstance(result, dict) else str(result)
        self.set_result(exchange, self.target, output)
