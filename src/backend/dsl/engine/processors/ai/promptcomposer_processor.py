"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

import re
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class PromptComposerProcessor(BaseProcessor):
    """Строит промпт из шаблона + контекст из exchange properties."""

    def __init__(
        self,
        template: str,
        context_property: str = "vector_results",
        output_property: str = "_composed_prompt",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._template = template
        self._context_property = context_property
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        ctx_data = exchange.properties.get(self._context_property, "")
        if isinstance(ctx_data, list):
            ctx_data = "\n---\n".join(
                item.get("document", str(item)) if isinstance(item, dict) else str(item)
                for item in ctx_data
            )
        body = exchange.in_message.body
        if isinstance(body, dict):
            variables = {**body, "context": ctx_data}
        else:
            variables = {"input": body, "context": ctx_data}
        try:
            prompt = self._template.format(**variables)
        except KeyError:
            # Extract variable names from template using regex
            vars_in_template = re.findall(
                r"\{([A-Za-z_][A-Za-z0-9_]*)\}", self._template
            )
            # Fill missing template vars with empty string (setdefault keeps real values)
            fill = {**variables}
            for k in vars_in_template:
                fill.setdefault(k, "")
            prompt = self._template.format_map(fill)
        exchange.set_property(self._output_property, prompt)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"template": self._template}
        if self._context_property != "vector_results":
            spec["context_property"] = self._context_property
        return {"compose_prompt": spec}
