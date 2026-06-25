"""S171 M8 — WorkflowConvertProcessor.

Конвертация между типами: JSON ↔ YAML ↔ dict ↔ pydantic.
Использует stdlib (json, yaml) + pydantic v2.

Pattern (Ponytail, D168): thin wrapper, no abstractions.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.workflow.convert")


class WorkflowConvertProcessor(BaseProcessor):
    """Конвертирует данные между форматами.

    Args:
        from_format: Исходный формат (``"json"``, ``"yaml"``, ``"dict"``).
        to_format: Целевой формат.
        source_property: Dotted path к данным в exchange (default ``"body"``).
        to: Куда записать результат (default ``"body.converted"``).
    """

    required_capability: str | None = "workflow.convert.format"
    audit_event: str | None = "workflow.convert.format"

    SUPPORTED = ("json", "yaml", "dict", "string")

    def __init__(
        self,
        *,
        from_format: str = "dict",
        to_format: str = "json",
        source_property: str = "body",
        to: str = "body.converted",
        name: str | None = None,
    ) -> None:
        if from_format not in self.SUPPORTED or to_format not in self.SUPPORTED:
            raise ValueError(
                f"WorkflowConvertProcessor: unsupported format "
                f"({from_format!r}→{to_format!r}). "
                f"Supported: {self.SUPPORTED}"
            )
        super().__init__(name=name or f"convert:{from_format}_to_{to_format}")
        self.from_format = from_format
        self.to_format = to_format
        self.source_property = source_property
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        # Resolve source from dotted path (simplified — just "body" or property)
        head, _, rest = self.source_property.partition(".")
        if head == "body":
            cursor: Any = exchange.in_message.body
            for part in rest.split(".") if rest else []:
                cursor = cursor.get(part) if isinstance(cursor, dict) else None
            data = cursor if cursor is not None else {}
        else:
            data = exchange.in_message.body

        def _convert() -> Any:
            # Normalize to intermediate dict
            if self.from_format == "json":
                if isinstance(data, str):
                    intermediate = json.loads(data)
                else:
                    intermediate = data  # assume already dict
            elif self.from_format == "yaml":
                import yaml  # PyYAML (already in deps)
                intermediate = yaml.safe_load(data) if isinstance(data, str) else data
            elif self.from_format == "string":
                intermediate = json.loads(data) if data else {}
            else:  # dict
                intermediate = data

            # Serialize to target
            if self.to_format == "json":
                return json.dumps(intermediate, ensure_ascii=False)
            if self.to_format == "yaml":
                import yaml
                return yaml.safe_dump(intermediate, allow_unicode=True)
            if self.to_format == "string":
                return json.dumps(intermediate)
            return intermediate  # dict

        # Conversion is sync; run in thread for large payloads
        import asyncio
        converted = await asyncio.to_thread(_convert)
        _logger.info(
            "workflow_convert %s→%s keys=%s",
            self.from_format, self.to_format,
            len(converted) if isinstance(converted, (str, list, dict)) else "?",
        )
        self.set_result(exchange, self.target, converted)