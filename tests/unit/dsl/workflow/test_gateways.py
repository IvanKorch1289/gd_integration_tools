"""Smoke-тесты workflow gateways (K3 W4).

Покрывает:
    * Компиляция XOR-gateway в exclusive-branching IR.
    * Компиляция AND-gateway в parallel wait_all IR.
    * Компиляция OR-gateway в inclusive wait_any IR.
    * BranchSpec с условием (condition не None).
    * Диспетчер process_gateway — маршрутизация по kind.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.workflow.gateways import (
    BranchSpec,
    GatewayCompiler,
    GatewaySpec,
    process_gateway,
)


def _make_branch(name: str, condition: str | None = None) -> BranchSpec:
    """Вспомогательный конструктор ветки с минимальными шагами."""
    return BranchSpec(
        name=name,
        condition=condition,
        steps=[{"type": "activity", "name": f"do_{name}"}],
    )


class TestGatewayXorCompilesToExclusiveBranching:
    """XOR-gateway компилируется в IR с strategy=exclusive."""

    def test_gateway_xor_compiles_to_exclusive_branching(self) -> None:
        """Результат compile_xor содержит strategy=exclusive и все ветки."""
        spec = GatewaySpec(
            kind="xor",
            branches=[
                _make_branch("high", condition="score > 0.8"),
                _make_branch("low", condition=None),
            ],
        )
        result = GatewayCompiler.compile_xor(spec)

        assert result["type"] == "gateway"
        assert result["strategy"] == "exclusive"
        assert len(result["branches"]) == 2
        assert result["branches"][0]["name"] == "high"
        assert result["branches"][0]["condition"] == "score > 0.8"
        assert result["branches"][1]["name"] == "low"
        assert result["branches"][1]["condition"] is None


class TestGatewayAndCompilesToParallelWaitAll:
    """AND-gateway компилируется в IR с strategy=parallel, join=wait_all."""

    def test_gateway_and_compiles_to_parallel_wait_all(self) -> None:
        """Результат compile_and содержит join=wait_all и все ветки."""
        spec = GatewaySpec(
            kind="and",
            branches=[
                _make_branch("notify_email"),
                _make_branch("notify_sms"),
                _make_branch("notify_push"),
            ],
        )
        result = GatewayCompiler.compile_and(spec)

        assert result["type"] == "gateway"
        assert result["strategy"] == "parallel"
        assert result["join"] == "wait_all"
        assert len(result["branches"]) == 3
        branch_names = [b["name"] for b in result["branches"]]
        assert "notify_email" in branch_names
        assert "notify_sms" in branch_names
        assert "notify_push" in branch_names


class TestGatewayOrCompilesToInclusiveWaitActive:
    """OR-gateway компилируется в IR с strategy=inclusive, join=wait_any."""

    def test_gateway_or_compiles_to_inclusive_wait_active(self) -> None:
        """Результат compile_or содержит join=wait_any."""
        spec = GatewaySpec(
            kind="or",
            branches=[
                _make_branch("fast_path", condition="latency_ms < 100"),
                _make_branch("slow_path", condition="latency_ms >= 100"),
            ],
        )
        result = GatewayCompiler.compile_or(spec)

        assert result["type"] == "gateway"
        assert result["strategy"] == "inclusive"
        assert result["join"] == "wait_any"
        assert len(result["branches"]) == 2


class TestBranchSpecWithCondition:
    """BranchSpec корректно хранит condition и steps."""

    def test_branch_spec_with_condition(self) -> None:
        """BranchSpec с явным условием сохраняет condition и steps без изменений."""
        steps = [
            {"type": "activity", "name": "fetch_score"},
            {"type": "sleep", "duration_s": 2.0},
        ]
        branch = BranchSpec(name="premium", condition="tier == 'premium'", steps=steps)

        assert branch.name == "premium"
        assert branch.condition == "tier == 'premium'"
        assert branch.steps == steps


class TestProcessGatewayDispatchesByKind:
    """process_gateway диспетчирует по kind к нужному компилятору."""

    @pytest.mark.parametrize(
        ("kind", "expected_strategy", "expected_join"),
        [
            ("xor", "exclusive", None),
            ("and", "parallel", "wait_all"),
            ("or", "inclusive", "wait_any"),
        ],
    )
    def test_process_gateway_dispatches_by_kind(
        self, kind: str, expected_strategy: str, expected_join: str | None
    ) -> None:
        """process_gateway возвращает корректный IR-dict для каждого kind."""
        spec = GatewaySpec(
            kind=kind,  # type: ignore[arg-type]
            branches=[_make_branch("a", condition="x > 0"), _make_branch("b")],
        )
        result = process_gateway(spec)

        assert result["type"] == "gateway"
        assert result["strategy"] == expected_strategy
        if expected_join is not None:
            assert result["join"] == expected_join
        else:
            assert "join" not in result
