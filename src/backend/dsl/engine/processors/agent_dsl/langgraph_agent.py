"""DSL processor ``langgraph_agent`` (Sprint 170 S170 — agent layer).

Thin wrapper над :func:`src.backend.services.ai.ai_graph.build_and_run_agent`
(LangGraph-backed ReAct-агент с tools).

Ponytail: 1-line DSL поверх существующей core-функции, без абстракций.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("LangGraphAgentProcessor",)
_logger = get_logger(__name__)


class LangGraphAgentProcessor(BaseAIProcessor):
    """Wraps LangGraph ReAct-agent через DSL.

    Args:
        query: Запрос агенту (или :class:`Expression` для runtime-resolve).
        to: Куда записать ``output`` агента (``body.field`` или property).
        thread_id: Optional thread-id (для checkpointing).
        max_iterations: Лимит LangGraph iterations (default 10).
    """

    required_capability: str | None = "agent.run"
    audit_event: str | None = "ai.agent.run"

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
        from src.backend.services.ai.ai_graph import build_and_run_agent
        result = await build_and_run_agent(
            query=self.query,
            thread_id=self.thread_id,
            max_iterations=self.max_iterations,
        )
        output = result.get("output", "") if isinstance(result, dict) else str(result)
        self.set_result(exchange, self.target, output)
