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


class InfraMixin:
    """Поведенческий миксин infra для :class:`RouteBuilder` (S51 W3)."""

    __slots__ = ()

    # --- AI infrastructure (guardrails_apply, pii_mask, pii_unmask, agent_graph, skill_invoke, ai_memory_recall, ai_memory_store, ai_rpa, mcp_tool, ai_tool_dispatch) ---

    def guardrails_apply(
        self,
        *,
        stage: str = "input",
        source_property: str | None = None,
        on_block: str = "warn",
        categories: list[str] | None = None,
    ) -> RouteBuilder:
        """Content safety через Llama Guard 3 (S27 W2).

        Args:
            stage: ``"input"`` (проверка prompt) или ``"output"`` (completion).
            source_property: Dot-path к тексту. Default зависит от ``stage``.
            on_block: ``"dlq"`` / ``"fail"`` / ``"warn"`` — политика при unsafe.
            categories: Опц. список категорий
                (default OAI moderation set от LlamaGuardRuntime).

        Example::

            builder.guardrails_apply(stage="output", on_block="fail")
        """
        from src.backend.dsl.engine.processors.agent_dsl.guardrails_apply import (
            GuardrailsApplyProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            GuardrailsApplyProcessor(
                stage=stage,
                source_property=source_property,
                on_block=on_block,
                categories=categories,
            )
        )

    def pii_mask(
        self,
        *,
        scope: str,
        source_property: str = "body",
        target_property: str | None = None,
        language: str = "ru",
    ) -> RouteBuilder:
        """Reversible PII tokenization через PIITokenizer (S27 W2, ADR-NEW-21).

        Args:
            scope: Capability scope (``"banking"`` / ``"hr"`` / ``"medical"``).
            source_property: Откуда взять текст. Default ``"body"``.
            target_property: Куда положить masked-текст. Default = source.
            language: Язык для Presidio NER. Default ``"ru"``.

        Example::

            builder.pii_mask(scope="banking")
        """
        from src.backend.dsl.engine.processors.agent_dsl.pii_mask import (
            PIIMaskProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            PIIMaskProcessor(
                scope=scope,
                source_property=source_property,
                target_property=target_property,
                language=language,
            )
        )

    def pii_unmask(
        self,
        *,
        source_property: str = "body",
        target_property: str | None = None,
        token_map_property: str = "pii_token_map",  # noqa: S107  # config field name, not a password
        scope: str = "default",
        strict: bool = False,
    ) -> RouteBuilder:
        """Восстановить PII по ``token_map`` от ``pii_mask`` (S27 W2).

        Args:
            source_property: Откуда взять masked-текст.
            target_property: Куда положить unmasked. Default = source.
            token_map_property: Где искать TokenMap. Default ``"pii_token_map"``.
            scope: Capability scope.
            strict: ``True`` — raise если token_map отсутствует.

        Example::

            builder.pii_unmask(source_property="agent_result.content", strict=True)
        """
        from src.backend.dsl.engine.processors.agent_dsl.pii_unmask import (
            PIIUnmaskProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            PIIUnmaskProcessor(
                source_property=source_property,
                target_property=target_property,
                token_map_property=token_map_property,
                scope=scope,
                strict=strict,
            )
        )

    def agent_graph(
        self,
        *,
        graph_type: str,
        model: str = "gpt-4o-mini",
        agents: list[dict[str, Any]] | None = None,
        prompt_inline: str | None = None,
        tool_actions: list[str] | None = None,
        max_handoffs: int = 5,
        result_property: str = "agent_graph_result",
        isolated: bool = False,
    ) -> RouteBuilder:
        """LangGraph execution as DSL step (S28 W4).

        Two modes:

        **Supervisor mode** (``graph_type="supervisor"``):
            LLM-driven multi-agent coordination via LangGraph StateGraph
            with handoff tools. Delegates to
            :class:`MultiAgentSupervisor <services.ai.multi_agent.supervisor>`.
            Each agent is a DSL workflow invoked via :class:`AgentRunProcessor`.

            Example::

                builder.agent_graph(
                    graph_type="supervisor",
                    agents=[
                        {"key": "scoring", "workflow_id": "credit_scoring",
                         "description": "Считает кредитный score"},
                        {"key": "decision", "workflow_id": "credit_decision",
                         "description": "Финальное решение"},
                    ],
                    max_handoffs=5,
                )

        **ReAct mode** (``graph_type="react"``):
            Tool-calling agent via ``langgraph.prebuilt.create_react_agent``.
            Delegates to :func:`services.ai.ai_graph.build_and_run_agent`.

            Example::

                builder.agent_graph(
                    graph_type="react",
                    prompt_inline="Найди информацию о заявке...",
                    tool_actions=["db.query", "http.get"],
                )

        Args:
            graph_type: ``"supervisor"`` or ``"react"``.
            model: LLM identifier. Default ``"gpt-4o-mini"``.
            agents: List of agent specs for supervisor mode.
                Each dict requires ``key``, ``workflow_id``, ``description``.
            prompt_inline: Inline prompt for react mode.
            tool_actions: Action names available as tools (react mode).
            max_handoffs: Maximum handoffs in supervisor mode. Default 5.
            result_property: Exchange property for result dict.
                Default ``"agent_graph_result"``.
            isolated: При True запускать ReAct-агента в отдельном процессе
                через :class:`ProcessPoolAgentSandbox`. Default False.
        """
        from src.backend.core.ai.agent_sandbox import (
            InProcessAgentSandbox,
            get_process_pool_agent_sandbox,
        )
        from src.backend.dsl.engine.processors.agent_dsl.agent_graph import (
            AgentGraphProcessor,
        )

        sandbox = (
            get_process_pool_agent_sandbox()
            if isolated
            else InProcessAgentSandbox()
        )

        return self._add(  # type: ignore[attr-defined]
            AgentGraphProcessor(
                graph_type=graph_type,
                model=model,
                agents=agents,
                prompt_inline=prompt_inline,
                tool_actions=tool_actions,
                max_handoffs=max_handoffs,
                result_property=result_property,
                sandbox=sandbox,
                isolated=isolated,
            )
        )

    def skill_invoke(
        self,
        *,
        skill_id: str,
        params_property: str | None = "body",
        result_property: str = "skill_result",
    ) -> RouteBuilder:
        """Вызов AI skill через :class:`SkillRegistry.invoke` (S27 W3, ADR-NEW-22).

        Args:
            skill_id: Идентификатор skill (``"credit.score.calculate"``).
            params_property: Откуда взять params (default ``"body"``).
            result_property: Свойство для результата (default ``"skill_result"``).

        Example::

            builder.skill_invoke(skill_id="credit.score.calculate")
        """
        from src.backend.dsl.engine.processors.agent_dsl.skill_invoke import (
            SkillInvokeProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            SkillInvokeProcessor(
                skill_id=skill_id,
                params_property=params_property,
                result_property=result_property,
            )
        )

    def ai_memory_recall(
        self,
        *,
        namespace: str,
        query: str | None = None,
        query_property: str | None = None,
        k: int = 5,
        result_property: str = "memory_recall",
    ) -> RouteBuilder:
        """RAG-style retrieval из :class:`MemoryProtocol` (S27 W3, ADR-NEW-18).

        Args:
            namespace: ``"<tenant_id>:<scope>"``. Поддерживает
                ``${tenant_id}`` placeholder.
            query: Опц. статичный запрос.
            query_property: Опц. dot-path к динамическому запросу.
            k: Максимум записей. Default ``5``.
            result_property: Свойство exchange для записей.

        Example::

            builder.ai_memory_recall(
                namespace="${tenant_id}:credit_chat",
                query_property="body.user_input",
                k=3,
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.memory_recall import (
            MemoryRecallProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            MemoryRecallProcessor(
                namespace=namespace,
                query=query,
                query_property=query_property,
                k=k,
                result_property=result_property,
            )
        )

    def ai_memory_store(
        self,
        *,
        namespace: str,
        key: str | None = None,
        key_property: str | None = None,
        value_property: str = "agent_result",
        ttl_s: int | None = None,
    ) -> RouteBuilder:
        """Запись в :class:`MemoryProtocol` (S27 W3, ADR-NEW-18).

        Args:
            namespace: ``"<tenant_id>:<scope>"``.
            key: Опц. статичный ключ.
            key_property: Опц. dot-path
                (``"meta.exchange_id"`` / ``"body.user_id"``).
            value_property: Откуда взять value (default ``"agent_result"``).
            ttl_s: Опц. TTL в секундах.

        Example::

            builder.ai_memory_store(
                namespace="${tenant_id}:credit_chat",
                key_property="meta.exchange_id",
                ttl_s=86400,
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.memory_store import (
            MemoryStoreProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            MemoryStoreProcessor(
                namespace=namespace,
                key=key,
                key_property=key_property,
                value_property=value_property,
                ttl_s=ttl_s,
            )
        )

    def ai_rpa(
        self,
        *,
        task: str,
        ui_context: dict[str, Any] | None = None,
        action_property: str = "ai_rpa.action",
        model: str = "gpt-4o",
        temperature: float = 0.1,
        to: str = "property:rpa.ai_decision",
    ) -> RouteBuilder:
        """AI-driven RPA action selection via LLM (S28 W5, wave:s8/k3-rpa-ai-decide).

        Анализирует задачу (natural language) и UI-контекст (screenshot/dom_snapshot)
        через LLM и возвращает структурированный RPA action для последующего
        выполнения через DesktopRpaProcessor или BrowserRpaProcessor.

        Args:
            task: Описание задачи на естественном языке.
            ui_context: Dict с UI-данными (``screenshot``, ``dom_snapshot``).
                Поддерживает property reference через ``${...}``.
            action_property: Exchange property для записи выбранного action.
            model: LLM model для принятия решений (default ``gpt-4o``).
            temperature: Temperature для LLM (default ``0.1``).
            to: Опц. путь записи результата
                (``body.<field>`` / ``property:<name>``).

        Example::

            builder.ai_rpa(
                task="Нажми кнопку 'Подтвердить' в диалоговом окне",
                ui_context={"screenshot": "${rpa.screenshot}"},
            )
        """
        from src.backend.dsl.engine.processors.ai_rpa import AIRpaProcessor

        return self._add(  # type: ignore[attr-defined]
            AIRpaProcessor(
                task=task,
                ui_context=ui_context,
                action_property=action_property,
                model=model,
                temperature=temperature,
                to=to,
            )
        )

    def mcp_tool(
        self,
        *,
        tool_uri: str,
        tool_name: str,
        arguments_property: str = "body",
        result_property: str = "mcp_result",
        timeout_s: float = 30.0,
    ) -> RouteBuilder:
        """Вызов MCP tool через FastMCP Client (S27 W3, S28 W5).

        Подключается к MCP-серверу по ``tool_uri`` и вызывает
        именованный tool с аргументами из ``arguments_property``.
        Результат записывается в ``result_property``.

        Args:
            tool_uri: URI MCP-сервера
                (``http://localhost:8000/mcp`` или ``file:///path/to/server.py``).
            tool_name: Имя вызываемого tool'а в MCP-сервере.
            arguments_property: Опц. путь к аргументам вызова
                (``body`` / ``body.<key>`` / ``property:<name>``).
                Default ``body`` — все тело сообщения как dict.
            result_property: Свойство exchange для записи результата.
                Default ``mcp_result``.
            timeout_s: Timeout на вызов в секундах. Default ``30``.

        Example::

            builder.mcp_tool(
                tool_uri="http://localhost:8000/mcp",
                tool_name="database.query",
                arguments_property="body.query_params",
                result_property="mcp_result",
            )
        """
        from src.backend.dsl.engine.processors.agent_dsl.mcp_tool import (
            MCPToolProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            MCPToolProcessor(
                tool_uri=tool_uri,
                tool_name=tool_name,
                arguments_property=arguments_property,
                result_property=result_property,
                timeout_s=timeout_s,
            )
        )

    def ai_tool_dispatch(
        self,
        *,
        available_tool_ids: list[str],
        query: str | None = None,
        query_property: str | None = None,
        result_property: str = "tool_dispatch_result",
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ) -> RouteBuilder:
        """LLM-orchestrated dispatch к одному tool из whitelist (S106 W4 / TD-009).

        Упрощённый single-shot ReAct: LLM выбирает tool из
        ``available_tool_ids`` (whitelist) и автоматически вызывает
        его через :class:`ToolRegistry`. Без цикла thought→action→observation,
        без LangGraph overhead.

        Args:
            available_tool_ids: Whitelist tool_id из
                :meth:`ToolRegistry.list`. LLM выбирает строго из этого
                списка (защита от prompt-injection: LLM не может вызвать
                произвольный tool).
            query: Статичный query для LLM. Взаимоисключающ с
                ``query_property``.
            query_property: Dot-path к динамическому query в exchange
                (``"body.user_input"`` / ``"property:user_query"``).
            result_property: Свойство exchange для dict-результата.
                Default ``"tool_dispatch_result"``.
            model: LLM model для tool selection. Default ``"gpt-4o-mini"``.
            temperature: LLM temperature. Default ``0.0`` (deterministic
                selection, минимум галлюцинаций).

        Example::

            builder.ai_tool_dispatch(
                available_tool_ids=[
                    "order_service.get",
                    "order_service.list",
                    "credit_service.score",
                ],
                query_property="body.user_request",
                result_property="dispatch_result",
            )

        Note:
            S106 W4 = skeleton: DSL method + validation + capability gate
            + audit emit. Real LLM-wiring (AIGateway.invoke + JSON-parse
            + auto-dispatch) — S106+ W5+ (multi-wave scope).
        """
        from src.backend.dsl.engine.processors.agent_dsl.ai_tool_dispatch import (
            AIToolDispatchProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            AIToolDispatchProcessor(
                available_tool_ids=available_tool_ids,
                query=query,
                query_property=query_property,
                result_property=result_property,
                model=model,
                temperature=temperature,
            )
        )
