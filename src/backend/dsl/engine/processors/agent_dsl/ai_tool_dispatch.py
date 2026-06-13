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
        """Skeleton: строит prompt, делегирует на AIGateway.

        S106 W4: real LLM-wiring — S106+ W5+ (multi-wave scope). Сейчас
        эмитим audit с outcome=scaffold и сохраняем placeholder.
        """
        del context
        query = self._resolve_query(exchange)
        if query is None:
            _logger.warning(
                "%s: query_property %r пуст — skip", self.name, self.query_property
            )
            exchange.set_property(
                self.result_property,
                {"dispatched": False, "reason": "empty_query"},
            )
            return

        # S106 W4: skeleton — реальный AIGateway.invoke() с JSON-tool-prompt
        # и последующим ToolRegistry.get(tool_id).callable(**args) —
        # следующая wave (S106+ W5+).
        tools_desc = self._resolve_tools_description()
        _logger.debug(
            "%s: scaffold — would dispatch LLM with tools=%s query=%r model=%s",
            self.name,
            self.available_tool_ids,
            query[:120],
            self.model,
        )
        exchange.set_property(
            self.result_property,
            {
                "dispatched": False,
                "reason": "scaffold",
                "hint": "real LLM wiring in S106+ W5+",
                "available_tools_count": len(self.available_tool_ids),
                "available_tools_description_chars": len(tools_desc),
                "query_chars": len(query),
            },
        )

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
