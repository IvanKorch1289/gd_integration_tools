"""AIToolDispatchProcessor — DSL-шаг LLM-orchestrated tool dispatch (S106 W4).

S106 W4 = TD-009 closure: LLM выбирает один tool из списка доступных
(:class:`ToolRegistry`) и автоматически вызывает его с сгенерированными
аргументами. Это упрощённый single-shot вариант ReAct pattern — без
цикла thought→action→observation, без LangGraph overhead.

Контракт
--------

* Caller задаёт ``available_tool_ids`` (подмножество
  :meth:`ToolRegistry.list`) — LLM выбирает строго из этого whitelist.
* LLM получает JSON-schema описания tools (id, description, parameters)
  и возвращает ``{"tool_id": ..., "args": {...}}``.
* Если LLM вернул ``tool_id=None`` / unknown — ``result_property`` = dict
  с ``{"dispatched": False, "reason": "no_tool"}``.
* Если LLM вернул валидный tool — ``result_property`` = ``{"dispatched":
  True, "tool_id": ..., "result": <tool_result>}``.

S106 W4 scope: DSL skeleton + constructor + canonical DSL method
``RouteBuilder.ai_tool_dispatch(...)``. Real AIGateway wiring
(LLM-вызов + JSON-парсинг + auto-dispatch) — S106+ W5+
(multi-wave scope). Сейчас ``_run`` помечает exchange ошибкой
``NotImplementedError`` (scaffold) и эмитит audit ``ai.tool.dispatch``
с outcome=scaffold.

Capability ``ai.tool.dispatch`` обязательна.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AIToolDispatchProcessor",)

_logger = get_logger(__name__)


class AIToolDispatchProcessor(BaseAIProcessor):
    """LLM-orchestrated dispatch к одному tool из whitelist (S106 W4).

    Args:
        available_tool_ids: Список tool_id из :class:`ToolRegistry.list()`
            которые LLM может выбрать. Если пустой — pass-through.
        query: Опц. статичный query для LLM.
        query_property: Опц. dot-path к динамическому query в exchange.
        result_property: Куда писать dict с результатом. Default
            ``"tool_dispatch_result"``.
        model: LLM model для selection. Default ``"gpt-4o-mini"``.
        temperature: LLM temperature. Default ``0.0`` (deterministic).
        name: Имя процессора.
    """

    required_capability: ClassVar[str | None] = "ai.tool.dispatch"
    audit_event: ClassVar[str | None] = "ai.tool.dispatch"

    def __init__(
        self,
        *,
        available_tool_ids: list[str],
        query: str | None = None,
        query_property: str | None = None,
        result_property: str = "tool_dispatch_result",
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        name: str | None = None,
    ) -> None:
        if not available_tool_ids:
            raise ValueError(
                "AIToolDispatchProcessor: available_tool_ids не может быть "
                "пустым (нет whitelist = нет dispatch)"
            )
        if query is None and query_property is None:
            raise ValueError(
                "AIToolDispatchProcessor: требуется query или query_property"
            )
        super().__init__(name=name or "ai_tool_dispatch")
        self.available_tool_ids = list(available_tool_ids)
        self.query = query
        self.query_property = query_property
        self.result_property = result_property
        self.model = model
        self.temperature = temperature

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope = список tool_ids (joined) для capability check."""
        del exchange
        return ",".join(sorted(self.available_tool_ids))

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Real LLM-wiring (S107 W4): prompt LLM с available_tools → parse → dispatch.

        Алгоритм:
        1. Resolve query (static или из exchange property);
        2. Build JSON-schema prompt: tools + query → LLM;
        3. Call ``AIGateway.invoke()`` (lazy resolve через DI);
        4. Parse ``AIResponse.content`` as JSON ``{"tool_id": ..., "args": {...}}``;
        5. ``ToolRegistry.get(tool_id).callable(**args)`` → result;
        6. Write ``{dispatched: True, tool_id, result}`` в ``result_property``.

        Graceful fallback: если LLM/Gateway/Registry недоступен —
        ``{dispatched: False, reason: "..."}`` (не raise, per audit
        requirement).
        """
        del context
        query = self._resolve_query(exchange)
        if query is None:
            _logger.warning(
                "%s: query_property %r пуст — skip", self.name, self.query_property
            )
            exchange.set_property(
                self.result_property, {"dispatched": False, "reason": "empty_query"}
            )
            return

        tools_desc = self._resolve_tools_description()
        selection = await self._ask_llm_for_tool_selection(
            query=query, tools_desc=tools_desc
        )
        if selection is None:
            # LLM unavailable, parse error, или не выбрал tool
            exchange.set_property(
                self.result_property,
                {
                    "dispatched": False,
                    "reason": selection_reason
                    if (selection_reason := "no_selection")
                    else "no_selection",
                    "query_chars": len(query),
                    "available_tools_count": len(self.available_tool_ids),
                },
            )
            return

        tool_id = selection.get("tool_id")
        tool_args = selection.get("args") or {}
        if not tool_id:
            exchange.set_property(
                self.result_property,
                {
                    "dispatched": False,
                    "reason": "llm_returned_no_tool",
                    "llm_selection": selection,
                },
            )
            return

        # Whitelist check: LLM не должен мочь вызвать tool вне whitelist
        # (defensive — even though мы передавали whitelist в prompt)
        if tool_id not in self.available_tool_ids:
            _logger.warning(
                "%s: LLM вернул tool_id=%r вне whitelist=%r — block",
                self.name,
                tool_id,
                self.available_tool_ids,
            )
            exchange.set_property(
                self.result_property,
                {
                    "dispatched": False,
                    "reason": "tool_id_not_in_whitelist",
                    "llm_tool_id": tool_id,
                },
            )
            return

        # Resolve tool from registry + invoke
        try:
            from src.backend.services.ai.tools.registry import get_tool_registry

            registry = get_tool_registry()
        except Exception as exc:
            _logger.debug("%s: ToolRegistry unavailable (%s) — skip", self.name, exc)
            registry = None

        if registry is None:
            exchange.set_property(
                self.result_property,
                {"dispatched": False, "reason": "tool_registry_unavailable"},
            )
            return

        tool = registry.get(tool_id)
        if tool is None:
            exchange.set_property(
                self.result_property,
                {
                    "dispatched": False,
                    "reason": "tool_not_in_registry",
                    "tool_id": tool_id,
                },
            )
            return

        try:
            tool_result = await tool.callable(**tool_args)
        except Exception as exc:
            _logger.warning(
                "%s: tool %r raised %s — record error", self.name, tool_id, exc
            )
            exchange.set_property(
                self.result_property,
                {
                    "dispatched": True,
                    "tool_id": tool_id,
                    "tool_error": str(exc),
                    "tool_error_class": type(exc).__name__,
                },
            )
            return

        exchange.set_property(
            self.result_property,
            {
                "dispatched": True,
                "tool_id": tool_id,
                "args": tool_args,
                "result": tool_result,
            },
        )

    async def _ask_llm_for_tool_selection(
        self, *, query: str, tools_desc: str
    ) -> dict[str, Any] | None:
        """Build prompt + call AIGateway + parse JSON tool selection.

        Returns:
            ``{"tool_id": str, "args": dict}`` или ``None`` если LLM
            недоступен / parse failed / LLM вернул ``tool_id: null``.
        """
        prompt = self._build_selection_prompt(query=query, tools_desc=tools_desc)
        try:
            from src.backend.core.ai.gateway import AIGateway
            from src.backend.core.ai.gateway_models import AIRequest
        except Exception as exc:
            _logger.debug("%s: AIGateway import failed (%s) — skip", self.name, exc)
            return None

        # Lazy AIRequest construction. tenant_id/correlation_id best-effort
        # (audit-sink в _base.AuditMixin.process подхватит их позже).
        try:
            gateway = AIGateway()
            request = AIRequest(
                workflow_id="ai_tool_dispatch",
                tenant_id="default",
                correlation_id="",
                prompt_inline=prompt,
                context={
                    "model": self.model,
                    "temperature": self.temperature,
                    "tools_desc": tools_desc,
                    "query": query,
                },
                stream=False,
            )
            response = await gateway.invoke(request)
        except Exception as exc:
            _logger.warning("%s: AIGateway.invoke failed (%s) — skip", self.name, exc)
            return None

        return self._parse_tool_selection(response.content)

    def _build_selection_prompt(self, *, query: str, tools_desc: str) -> str:
        """Build prompt asking LLM to pick a tool from available_tool_ids.

        Output format: JSON ``{"tool_id": "<id>|null, "args": {...}}``.
        LLM может вернуть ``null`` если ни один tool не подходит.
        """
        # Используем literal JSON markers для надёжного парсинга.
        return (
            "You are a tool dispatcher. Given a user query and a list of "
            "available tools (JSON schema), select the most appropriate tool "
            "and extract its arguments.\n\n"
            "## User Query\n"
            f"{query}\n\n"
            "## Available Tools\n"
            f"```json\n{tools_desc}\n```\n\n"
            "## Response Format\n"
            "Return ONLY a JSON object with this exact schema:\n"
            "```json\n"
            '{"tool_id": "<one of the available tool ids, or null if none fit>", '
            '"args": {<key-value pairs matching the chosen tool\'s parameters>}\n'
            "}\n```\n\n"
            "Do not include any explanation, only the JSON object."
        )

    def _parse_tool_selection(self, content: str) -> dict[str, Any] | None:
        """Parse LLM response content as JSON tool selection.

        Robust: handles ```json ... ``` fences, leading/trailing
        whitespace, и bare JSON. Returns ``None`` on parse failure
        или если LLM явно вернул ``null`` tool_id.
        """
        import json
        import re

        # Strip markdown code fences if present
        text = content.strip()
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m is not None:
            text = m.group(1)
        # Trim again (после fence removal)
        text = text.strip()
        if not text or text == "null":
            return None
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError) as exc:
            _logger.debug(
                "%s: LLM response JSON parse failed (%s): %r",
                self.name,
                exc,
                text[:200],
            )
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def _resolve_query(self, exchange: Exchange[Any]) -> str | None:
        """Получить query: статичный → из property → None."""
        if self.query is not None:
            return self.query
        if self.query_property is not None:
            value = exchange.get_property(self.query_property)
            return str(value) if value is not None else None
        return None

    def _resolve_tools_description(self) -> str:
        """Сериализует whitelist tools в JSON-schema описание.

        Поддерживает lazy-resolution :class:`ToolRegistry` — если
        registry недоступен (DI=None, scaffold-режим), возвращает
        generic-описание из tool_ids (без parameters).
        """
        try:
            from src.backend.services.ai.tools.registry import get_tool_registry

            registry = get_tool_registry()
        except Exception as _:
            registry = None

        if registry is None:
            return json.dumps(
                [{"id": tid, "available": True} for tid in self.available_tool_ids]
            )

        tools_spec: list[dict[str, Any]] = []
        for tid in self.available_tool_ids:
            tool = registry.get(tid)
            if tool is None:
                tools_spec.append({"id": tid, "available": False})
                continue
            tools_spec.append(
                {
                    "id": tool.id,
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            )
        return json.dumps(tools_spec, ensure_ascii=False)

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML.

        В spec попадает только непустой whitelist и кастомные properties
        (минимальный YAML, defaults опущены).
        """
        spec: dict[str, Any] = {"available_tool_ids": list(self.available_tool_ids)}
        if self.query is not None:
            spec["query"] = self.query
        if self.query_property is not None:
            spec["query_property"] = self.query_property
        if self.result_property != "tool_dispatch_result":
            spec["result_property"] = self.result_property
        if self.model != "gpt-4o-mini":
            spec["model"] = self.model
        if self.temperature != 0.0:
            spec["temperature"] = self.temperature
        return {"ai_tool_dispatch": spec}
