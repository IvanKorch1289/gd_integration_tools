"""Async runtime compilers для BPMN gateways (cycle 33 restore, closes P0 #8 + #9).

PLAN V17 [wave:s3/workflow-gateways], K3 W4 — runtime-часть.

Три компилятора соответствуют BPMN 2.0 gateway-элементам, сериализованным
BPMN-импортёром в ``ActivityDeclaration.args["gateway"]`` (либо как
:class:`~dsl.workflow.gateways.GatewaySpec` instance, либо как dict с
``kind`` + ``branches``).

Семантика:
    * :func:`compile_xor` — exclusive: первая ветка с истинным ``condition``.
    * :func:`compile_and` — parallel: ``asyncio.gather`` всех веток (join-all).
    * :func:`compile_or`  — race: ``asyncio.wait(FIRST_COMPLETED)`` +
      ``task.cancel()`` для pending.

Каждый ``BranchSpec.steps`` — список :class:`ActivityDeclaration` или
marker-dict (``{"bpmn_target": target_id}``). На исполнение идут только
ActivityDeclaration; marker-dict игнорируются (compile-time markers
для BPMN topology, не runtime steps).
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.workflow.gateways import BranchSpec, GatewaySpec
from src.backend.dsl.workflow.spec import ActivityDeclaration

__all__ = (
    "compile_and",
    "compile_or",
    "compile_xor",
)

_logger = get_logger("workflow.compiler.gateways")


def _resolve_gateway_spec(decl: ActivityDeclaration) -> GatewaySpec:
    """Извлечь :class:`GatewaySpec` из ``ActivityDeclaration.args['gateway']``.

    Поддерживает live :class:`GatewaySpec` instance (от Python-builder) и
    dict-вариант от BPMN-импортёра (см. ``bpmn_importer._gateway_spec_to_dict``).
    """
    gw_raw = decl.args["gateway"]
    if isinstance(gw_raw, GatewaySpec):
        return gw_raw
    if isinstance(gw_raw, dict):
        return GatewaySpec(
            kind=gw_raw["kind"],
            branches=[
                BranchSpec(
                    name=b["name"],
                    condition=b.get("condition"),
                    steps=list(b.get("steps", [])),
                )
                for b in gw_raw["branches"]
            ],
        )
    raise TypeError(
        f"Unsupported gateway payload type: {type(gw_raw)!r}; "
        "expected GatewaySpec or dict",
    )


def _eval_condition(condition: str | None, ctx: dict[str, Any]) -> bool:
    """Оценить condition-выражение против контекста workflow.

    Использует :class:`simpleeval.SimpleEval` (sandbox-safe) с
    namespace из ``ctx['_outputs']``: ключи outputs становятся
    переменными выражения. Eval-failure → ``False`` (защита от typos).

    NOTE: full JMESPath-поддержка — out of scope для cycle 33; достаточно
    для простых boolean expressions (``flag_a``, ``score > 0.8``).
    """
    if condition is None:
        return True  # default branch — fallback
    outputs = ctx.get("_outputs", {})
    namespace: dict[str, Any] = {**outputs}
    try:
        from simpleeval import SimpleEval  # S4 R-V15-4: lazy-import

        return bool(SimpleEval(names=namespace).eval(condition))
    except Exception as exc:
        _logger.warning(
            "gateway condition eval failed: condition=%r err=%s; treating as False",
            condition,
            exc,
        )
        return False


async def _run_branch_steps(
    branch: BranchSpec, ctx: dict[str, Any],
) -> Any:
    """Выполнить шаги одной ветки последовательно.

    Поддерживает ``ActivityDeclaration`` instance напрямую; dict'ы
    конвертируются в :class:`ActivityDeclaration` если имеют
    ``type='activity'`` и валидные поля. Прочие dict'ы (marker-only) —
    silent skip (compile-time topology markers, не runtime steps).
    """
    from src.backend.dsl.workflow.compiler.step_compilers import compile_activity_step

    result: Any = None
    for step in branch.steps:
        if isinstance(step, ActivityDeclaration):
            result = await compile_activity_step(step, ctx)
        elif isinstance(step, dict) and step.get("type") == "activity":
            result = await compile_activity_step(
                ActivityDeclaration(
                    name=step["name"],
                    args=step.get("args", {}),
                    timeout_s=step.get("timeout_s"),
                    output_key=step.get("output_key"),
                ),
                ctx,
            )
        # else: marker dict ({"bpmn_target": ...}) — no runtime action
    return result


async def compile_xor(decl: ActivityDeclaration, ctx: dict[str, Any]) -> Any:
    """XOR (exclusive) gateway: первая matched-ветка, default — fallback.

    Семантика: итерация по веткам в порядке объявления; первая ветка с
    ``condition`` evaluates to ``True`` исполняется; остальные
    игнорируются. Если ни одна ветка с explicit condition не matched —
    выполняется первая ветка с ``condition=None`` (default branch).

    Args:
        decl: ActivityDeclaration с ``args['gateway']`` = XOR GatewaySpec.
        ctx: Рантайм-контекст workflow.

    Returns:
        Имя выполненной ветки (``branch.name``), либо ``None`` если
        ни одна ветка не matched и нет default.
    """
    spec = _resolve_gateway_spec(decl)
    default_branch: BranchSpec | None = None

    for branch in spec.branches:
        if branch.condition is None:
            # Запоминаем default; не выполняем до конца итерации (exclusive).
            if default_branch is None:
                default_branch = branch
            continue
        if _eval_condition(branch.condition, ctx):
            await _run_branch_steps(branch, ctx)
            return branch.name

    if default_branch is not None:
        await _run_branch_steps(default_branch, ctx)
        return default_branch.name
    return None


async def compile_and(decl: ActivityDeclaration, ctx: dict[str, Any]) -> Any:
    """AND (parallel) gateway: все ветки параллельно, join-all.

    Семантика: ``asyncio.gather`` всех веток — workflow продолжается
    только после завершения **всех** веток. Если любая ветка бросила
    exception — gather re-raises (first failure), остальные ветки
    продолжают работу в фоне (asyncio.gather semantics).

    Args:
        decl: ActivityDeclaration с ``args['gateway']`` = AND GatewaySpec.
        ctx: Рантайм-контекст workflow.

    Returns:
        Список результатов всех веток (в порядке объявления).
    """
    spec = _resolve_gateway_spec(decl)
    if not spec.branches:
        return []
    coros = [_run_branch_steps(branch, ctx) for branch in spec.branches]
    return await asyncio.gather(*coros)


async def compile_or(decl: ActivityDeclaration, ctx: dict[str, Any]) -> Any:
    """OR (inclusive) gateway: race, cancel remaining on first complete.

    Семантика: каждая ветка запускается как отдельная ``asyncio.Task``;
    ``asyncio.wait(FIRST_COMPLETED)`` resolves когда **первая** ветка
    завершается (success или exception). Все pending tasks получают
    ``task.cancel()`` + await для подавления CancelledError-warning.

    Args:
        decl: ActivityDeclaration с ``args['gateway']`` = OR GatewaySpec.
        ctx: Рантайм-контекст workflow.

    Returns:
        Результат первой завершённой ветки, либо ``None`` если веток нет.
    """
    spec = _resolve_gateway_spec(decl)
    if not spec.branches:
        return None

    tasks: list[asyncio.Task[Any]] = [
        asyncio.create_task(_run_branch_steps(branch, ctx))
        for branch in spec.branches
    ]

    done, pending = await asyncio.wait(
        tasks, return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
    # Drain cancelled tasks для подавления "Task was destroyed but it
    # is pending!" warnings; CancelledError ожидаемо и обработано.
    for task in pending:
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Возвращаем первый успешный result; если done-task упал — propagate.
    for task in done:
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            raise exc
        return task.result()
    return None
