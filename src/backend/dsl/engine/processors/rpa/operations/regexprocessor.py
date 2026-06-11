from __future__ import annotations

"""S65 W2 — RegexProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class RegexProcessor(BaseProcessor):
    """Regex операции: extract, replace, match.

    action="extract": возвращает все совпадения.
    action="replace": заменяет совпадения на replacement.
    action="match": True/False (останавливает pipeline если нет совпадения).
    """

    def __init__(
        self,
        pattern: str,
        *,
        action: str = "extract",
        replacement: str = "",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"regex:{action}")
        self._pattern = pattern
        self._action = action
        self._replacement = replacement

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        import re

        body = exchange.in_message.body
        text = body if isinstance(body, str) else str(body)
        if self._action == "extract":
            matches = re.findall(self._pattern, text)
            exchange.set_out(body=matches, headers=dict(exchange.in_message.headers))
        elif self._action == "replace":
            result = re.sub(self._pattern, self._replacement, text)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
        elif self._action == "match":
            if not re.search(self._pattern, text):
                exchange.set_property("regex_matched", False)
                exchange.stop()
            else:
                exchange.set_property("regex_matched", True)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {"pattern": self._pattern}
        if self._action != "extract":
            spec["action"] = self._action
        if self._replacement != "":
            spec["replacement"] = self._replacement
        return {"regex": spec}
