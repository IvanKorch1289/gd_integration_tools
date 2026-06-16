"""Structural protocol for LLMStructuredProcessor mixins.

Breaks the circular dependency between ``LLMStructuredProcessor`` and its
mixins and gives mypy enough information about the private attributes/helpers
the mixins use.
"""

from __future__ import annotations

from typing import Any, Protocol


class _LLMStructuredProcessorProtocol(Protocol):
    """Common shape expected by LLMStructuredProcessor mixins."""

    _model: str
    _output_schema_ref: Any
    _prompt_template: str
    _retry: int
    _temperature: float
    _cost_budget_usd: float | None
    _to: str

    def _resolve_schema(self) -> Any: ...

    def _resolve_prompt(self, exchange: Any) -> str: ...

    def _provider_name(self) -> str: ...

    def _estimate_cost(self, usage: Any) -> float: ...

    def _extract_tokens(self, response: Any) -> dict[str, int]: ...

    def _write_result(self, exchange: Any, result: Any) -> None: ...

    async def _call_with_completion(self, exchange: Any, context: Any) -> Any: ...
