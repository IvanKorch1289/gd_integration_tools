from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Self

from src.backend.dsl.workflow.spec import MemoryScope

if TYPE_CHECKING:
    pass


class AiAgentMixin:
    """AI agent invocation (BIG 66 LOC) для WorkflowBuilder. S58 W4 extraction."""

    __slots__ = ()

    def invoke_agent(
        self,
        agent_id: str,
        *,
        input_context: str | None = None,
        durable: bool = False,
        output_key: str | None = None,
        max_turns: int = 10,
        timeout_s: float | None = None,
        memory_scope: MemoryScope | None = None,
        write_episode: bool = False,
        namespace_template: str | None = None,
        inject_memory: bool = False,
        recall_on: str | None = None,
    ) -> Self:
        """Добавить AI-агент как шаг workflow (S27 W6, S28 W2, R-V15-9).

        При ``durable=False``: stateless call через
        :meth:`AIGateway.invoke() <src.backend.core.ai.gateway.AIGateway.invoke>`.
        При ``durable=True``: использует LangGraph Checkpointer
        (требует ``feature_flags.langgraph_postgres_checkpoint=True``;
        fallback на stateless при отсутствии).

        S28 W2 добавляет memory orchestration:
        * ``memory_scope`` — какие memory resources читать/писать;
        * ``write_episode`` — записать результат в episodic memory;
        * ``namespace_template`` — namespace для memory resources;
        * ``inject_memory`` — inject recalled facts в context агента;
        * ``recall_on`` — trigger condition для recall.

        Args:
            agent_id: Имя агента (``skill_id`` из SkillRegistry или
                ``workflow_id`` из LangGraph).
            input_context: Опц. dot-path или ``${...}`` выражение для
                извлечения input context из workflow-аргументов.
            durable: При True — LangGraph checkpoint persistence.
            output_key: Опц. имя property для сохранения результата.
            max_turns: Максимум turns в agent conversation (default 10).
            timeout_s: Per-invocation timeout (None → workflow-default).
            memory_scope: Memory scope для агента (S28 W2).
            write_episode: При True — записать результат в episodic memory.
            namespace_template: Шаблон namespace для memory resources.
            inject_memory: При True — inject recalled facts в context.
            recall_on: Dot-path trigger для recall (если None — всегда).

        Returns:
            Self для chain.
        """
        from src.backend.dsl.workflow.spec import AgentInvokeDeclaration

        self._steps.append(
            AgentInvokeDeclaration(
                agent_id=agent_id,
                input_context=input_context,
                durable=durable,
                output_key=output_key,
                max_turns=max_turns,
                timeout_s=timeout_s,
                memory_scope=memory_scope,
                write_episode=write_episode,
                namespace_template=namespace_template,
                inject_memory=inject_memory,
                recall_on=recall_on,
            )
        )
        return self
