"""S175 Phase 2: FormatterProcessor (full implementation).

Split из patterns.py godfile.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.patterns._helpers import _SafeDict

__all__ = ("FormatterProcessor",)


class FormatterProcessor(BaseProcessor):
    """Zapier Formatter — форматирует строку из body и properties.

    Template использует {field} для подстановки из body (dict)
    или {_property_name} для подстановки из exchange.properties.

    Usage::

        .format_text("Order {order_id} from {_user_email}")
    """

    def __init__(
        self,
        template: str,
        *,
        output_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"format_text:{template[:30]}")
        self._template = template
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Форматирует строку по шаблону, подставляя body и properties."""
        body = exchange.in_message.body
        variables: dict[str, Any] = {}
        if isinstance(body, dict):
            variables.update(body)
        for key, value in exchange.properties.items():
            if not key.startswith("_"):
                variables[key] = value
            else:
                variables[key] = value

        try:
            result = self._template.format_map(_SafeDict(variables))
        except (KeyError, ValueError, IndexError) as exc:
            exchange.fail(f"FormatterProcessor failed: {exc}")
            return

        if self._output_property:
            exchange.set_property(self._output_property, result)
        else:
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
