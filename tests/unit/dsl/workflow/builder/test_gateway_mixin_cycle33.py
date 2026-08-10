"""Тесты :class:`GatewayMixin` (cycle 33 restore, closes P0 #8 + #9).

Три теста покрывают:
    * XOR (exclusive) — первая ветка с истинным ``condition``,
      default-ветка (``condition=None``) — fallback.
    * AND (parallel) — ``asyncio.gather`` всех веток, join-all.
    * OR (inclusive) — ``asyncio.wait(FIRST_COMPLETED)`` + cancel losers.

Тесты идут через builder (``gateway_xor/and/or``) → ``compile_xor/and/or``
напрямую (без реального Temporal). ``compile_activity_step`` подменяется
на уровне модуля ``gateways.py`` для детерминированной записи вызовов.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.compiler import gateways as gw_compilers
from src.backend.dsl.workflow.compiler.gateways import (
    compile_and,
    compile_or,
    compile_xor,
)
from src.backend.dsl.workflow.gateways import BranchSpec, GatewaySpec
from src.backend.dsl.workflow.spec import ActivityDeclaration


def _gateway_decl(builder: WorkflowBuilder) -> ActivityDeclaration:
    """Извлечь последний gateway-step (ActivityDeclaration с args['gateway'])."""
    last = builder._steps[-1]
    assert isinstance(last, ActivityDeclaration)
    assert last.args and "gateway" in last.args
    return last


# ---------- XOR (exclusive): первая matched-ветка ----------


@pytest.mark.asyncio
async def test_gateway_xor_first_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """XOR: первая ветка с истинным condition выполняется; остальные — нет.

    B-08/B-09 fix (cycle 33): exclusive-routing. Ветка с condition=None
    (default) выполняется ТОЛЬКО если ни одна explicit-condition ветка
    не matched.
    """
    executed: list[str] = []

    async def fake_compile_activity_step(
        decl: ActivityDeclaration, ctx: dict[str, Any],
    ) -> str:
        executed.append(decl.name)
        outputs = ctx.setdefault("_outputs", {})
        outputs[decl.name] = True
        return decl.name

    # Patch на уровне step_compilers (gateways.py импортирует оттуда).
    import src.backend.dsl.workflow.compiler.step_compilers as sc

    monkeypatch.setattr(sc, "compile_activity_step", fake_compile_activity_step)

    builder = (
        WorkflowBuilder("xor.flow")
        .gateway_xor(
            BranchSpec(
                name="premium",
                condition="flag_premium",
                steps=[ActivityDeclaration(name="route.premium")],
            ),
            BranchSpec(
                name="standard",
                condition="flag_standard",
                steps=[ActivityDeclaration(name="route.standard")],
            ),
            BranchSpec(
                name="default",
                condition=None,
                steps=[ActivityDeclaration(name="route.default")],
            ),
        )
    )

    decl = _gateway_decl(builder)
    ctx: dict[str, Any] = {"_outputs": {"flag_premium": True}}

    result = await compile_xor(decl, ctx)

    # Только premium ветка выполнилась; default — fallback, не сработал.
    assert result == "premium"
    assert executed == ["route.premium"]


@pytest.mark.asyncio
async def test_gateway_xor_default_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """XOR default: ни одна condition-ветка не matched → default-ветка побеждает."""
    executed: list[str] = []

    async def fake_compile_activity_step(
        decl: ActivityDeclaration, ctx: dict[str, Any],
    ) -> str:
        executed.append(decl.name)
        return decl.name

    import src.backend.dsl.workflow.compiler.step_compilers as sc

    monkeypatch.setattr(sc, "compile_activity_step", fake_compile_activity_step)

    builder = WorkflowBuilder("xor.fallback").gateway_xor(
        BranchSpec(
            name="cond",
            condition="never_true",
            steps=[ActivityDeclaration(name="never")],
        ),
        BranchSpec(
            name="default",
            condition=None,
            steps=[ActivityDeclaration(name="fallback.step")],
        ),
    )

    decl = _gateway_decl(builder)
    ctx: dict[str, Any] = {"_outputs": {}}

    result = await compile_xor(decl, ctx)

    assert result == "default"
    assert executed == ["fallback.step"]


# ---------- AND (parallel): все ветки параллельно ----------


@pytest.mark.asyncio
async def test_gateway_and_waits_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AND: asyncio.gather — все ветки выполняются, join-all.

    B-08 fix (cycle 33): parallel fan-out через asyncio.gather.
    Проверяем что ВСЕ ветки выполнились.
    """
    executed: list[str] = []

    async def fake_compile_activity_step(
        decl: ActivityDeclaration, ctx: dict[str, Any],
    ) -> str:
        executed.append(decl.name)
        return decl.name

    import src.backend.dsl.workflow.compiler.step_compilers as sc

    monkeypatch.setattr(sc, "compile_activity_step", fake_compile_activity_step)

    builder = WorkflowBuilder("and.flow").gateway_and(
        BranchSpec(
            name="email",
            condition=None,
            steps=[ActivityDeclaration(name="notify.email")],
        ),
        BranchSpec(
            name="sms",
            condition=None,
            steps=[ActivityDeclaration(name="notify.sms")],
        ),
        BranchSpec(
            name="push",
            condition=None,
            steps=[ActivityDeclaration(name="notify.push")],
        ),
    )

    decl = _gateway_decl(builder)
    ctx: dict[str, Any] = {}

    result = await compile_and(decl, ctx)

    # Все три ветки выполнились (asyncio.gather preserves declaration order).
    assert executed == ["notify.email", "notify.sms", "notify.push"]
    # gather возвращает список результатов в порядке объявления веток.
    # Каждый branch result = last step result (fake_compile returns decl.name).
    assert result == ["notify.email", "notify.sms", "notify.push"]


# ---------- OR (inclusive): race + cancel losers ----------


@pytest.mark.asyncio
async def test_gateway_or_cancels_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OR: asyncio.wait(FIRST_COMPLETED) — первая ветка побеждает, остальные cancelled.

    B-09 fix (cycle 33): inclusive race. Cancel pending tasks через
    ``task.cancel()`` после FIRST_COMPLETED.
    """
    executed: list[str] = []
    cancel_observed: list[str] = []

    async def fake_compile_activity_step(
        decl: ActivityDeclaration, ctx: dict[str, Any],
    ) -> str:
        executed.append(decl.name)
        if decl.name == "fast":
            return decl.name
        # Slow branches — дожидаемся отмены.
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancel_observed.append(decl.name)
            raise
        return decl.name

    import src.backend.dsl.workflow.compiler.step_compilers as sc

    monkeypatch.setattr(sc, "compile_activity_step", fake_compile_activity_step)

    builder = WorkflowBuilder("or.flow").gateway_or(
        BranchSpec(
            name="fast_path",
            condition=None,
            steps=[ActivityDeclaration(name="fast")],
        ),
        BranchSpec(
            name="slow_path_1",
            condition=None,
            steps=[ActivityDeclaration(name="slow1")],
        ),
        BranchSpec(
            name="slow_path_2",
            condition=None,
            steps=[ActivityDeclaration(name="slow2")],
        ),
    )

    decl = _gateway_decl(builder)
    ctx: dict[str, Any] = {}

    # Запускаем compile_or с защитой от зависания в slow-ветках.
    result = await asyncio.wait_for(
        compile_or(decl, ctx), timeout=2.0,
    )

    # Первая завершённая ветка — fast (activity result fake_compile returned).
    assert result == "fast"
    # fast отработал, slow-ветки получили CancelledError (отменены
    # после FIRST_COMPLETED через task.cancel()).
    assert "fast" in executed
    assert "slow1" in cancel_observed
    assert "slow2" in cancel_observed


# ---------- Доп. smoke: builder method push правильный step ----------


def test_gateway_mixin_pushes_activity_declaration_with_gateway_arg() -> None:
    """Builder пушит ActivityDeclaration с args['gateway'] = GatewaySpec."""
    builder = WorkflowBuilder("smoke").gateway_xor(
        BranchSpec(
            name="a",
            condition="flag",
            steps=[ActivityDeclaration(name="do.a")],
        ),
    )

    assert len(builder._steps) == 1
    step = builder._steps[0]
    assert isinstance(step, ActivityDeclaration)
    assert step.name.startswith("__gateway__xor_")
    assert isinstance(step.args, dict)
    assert "gateway" in step.args
    gw = step.args["gateway"]
    assert isinstance(gw, GatewaySpec)
    assert gw.kind == "xor"
    assert len(gw.branches) == 1


def test_gateway_mixin_and_and_or_set_correct_kind() -> None:
    """builder.gateway_and / gateway_or пушат step с kind=and / or."""
    and_builder = WorkflowBuilder("and.smoke").gateway_and(
        BranchSpec(
            name="x",
            condition=None,
            steps=[ActivityDeclaration(name="x.step")],
        ),
    )
    or_builder = WorkflowBuilder("or.smoke").gateway_or(
        BranchSpec(
            name="y",
            condition=None,
            steps=[ActivityDeclaration(name="y.step")],
        ),
    )

    assert and_builder._steps[0].args["gateway"].kind == "and"
    assert or_builder._steps[0].args["gateway"].kind == "or"


# Suppress unused-import warning (gw_compilers is used for type clarity).
_ = gw_compilers
