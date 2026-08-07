"""D-A8-07 fix (cycle 1): GuardrailDeclaration fail-CLOSED при non-numeric.

Banking context critical: раньше compile_guardrail_step fallback к 0.0
при non-numeric value (dict/str/None) → silent fail-OPEN → guardrail
PASS даже при cost explosion (banking context).

Фикс: raise GuardrailValueTypeError при non-numeric value.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.dsl.workflow.compiler.step_compilers import (
    GuardrailValueTypeError,
    compile_guardrail_step,
)
from src.backend.dsl.workflow.spec.advanced_declarations import (
    GuardrailDeclaration,
)


def _make_decl(
    *,
    rule: str = "max_cost_usd",
    threshold: float = 100.0,
    target: str | None = "outputs.cost",
    on_exceed: str = "fail",
) -> GuardrailDeclaration:
    return GuardrailDeclaration(
        rule=rule,
        threshold=threshold,
        target=target,
        on_exceed=on_exceed,
    )


class TestGuardrailFailClosedOnNonNumeric:
    """D-A8-07 fix (cycle 1): GuardrailDeclaration fail-CLOSED."""

    @pytest.mark.asyncio
    async def test_string_value_raises(self) -> None:
        """Non-numeric string value → raise GuardrailValueTypeError."""
        decl = _make_decl()
        ctx = {"_outputs": {"cost": "expensive_string"}}

        with pytest.raises(GuardrailValueTypeError) as exc_info:
            await compile_guardrail_step(decl, ctx)

        assert "max_cost_usd" in str(exc_info.value)
        assert "expected numeric" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dict_value_raises(self) -> None:
        """Non-numeric dict value → raise GuardrailValueTypeError."""
        decl = _make_decl(target="outputs.metrics")
        ctx = {"_outputs": {"metrics": {"cpu": 80, "memory": 70}}}

        with pytest.raises(GuardrailValueTypeError):
            await compile_guardrail_step(decl, ctx)

    @pytest.mark.asyncio
    async def test_none_value_raises(self) -> None:
        """None value → raise GuardrailValueTypeError."""
        decl = _make_decl()
        ctx = {"_outputs": {"cost": None}}

        with pytest.raises(GuardrailValueTypeError):
            await compile_guardrail_step(decl, ctx)

    @pytest.mark.asyncio
    async def test_numeric_value_succeeds(self) -> None:
        """Numeric (int/float) value → succeed (regression test)."""
        decl = _make_decl(threshold=100.0, target=None)

        # Below threshold
        ctx_low = {"_outputs": {"cost": 50.0}}
        result = await compile_guardrail_step(decl, ctx_low)
        assert result["exceeded"] is False

        # Above threshold
        ctx_high = {"_outputs": {"cost": 150.0}}
        # on_exceed='fail' → RuntimeError (NOT GuardrailValueTypeError)
        with pytest.raises(RuntimeError, match="exceeded"):
            await compile_guardrail_step(decl, ctx_high)

    @pytest.mark.asyncio
    async def test_integer_value_accepted(self) -> None:
        """Integer values должны приниматься (не только float)."""
        decl = _make_decl(threshold=100, target=None)

        ctx = {"_outputs": {"cost": 50}}  # int, не float
        result = await compile_guardrail_step(decl, ctx)
        assert result["value"] == 50.0  # cast к float
        assert result["exceeded"] is False

    @pytest.mark.asyncio
    async def test_dlq_action_with_non_numeric_raises(self) -> None:
        """Даже с on_exceed='dlq' — non-numeric должно raise (fail-CLOSED до проверки threshold)."""
        decl = _make_decl(on_exceed="dlq")
        ctx = {"_outputs": {"cost": {"complex": "object"}}}

        with pytest.raises(GuardrailValueTypeError):
            await compile_guardrail_step(decl, ctx)
