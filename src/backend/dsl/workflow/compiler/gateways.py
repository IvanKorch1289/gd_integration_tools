"""Async runtime compilers для BPMN gateways (cycle 33 restore, closes P0 #8 + #9).

PLAN V17 [wave:s3/workflow-gateways], K3 W4 — runtime-часть.

Три компилятора соответствуют BPMN 2.0 gateway-элементам, сериализованным
BPMN-импортёром в ``ActivityDeclaration.args["gateway"]`` (либо как
:class:`~dsl.workflow.gateways.GatewaySpec` instance, либо как dict с
``kind`` + ``branches``).

Семантика:
    * :func:`compile_xor` — exclusive: первая ветка с истинным ``condition``.
    * :func:`compile_and` — parallel: ветки стартуют параллельно, join-all
      через ``workflow.wait`` (Temporal-детерминированная замена
      ``asyncio.wait``/``asyncio.gather``).
    * :func:`compile_or`  — race: ``workflow.wait(FIRST_COMPLETED)`` +
      ``task.cancel()`` для pending; победитель выбирается детерминированно
      (первая успешная ветка в порядке объявления).

ADR-0395: ``asyncio.wait`` рестритктуется Temporal-sandbox'ом
(``temporalio/worker/workflow_sandbox/_restrictions.py``) как
недетерминированный API, а ``asyncio.gather``/``create_task`` не дают
стабильного порядка событий при replay'е. Все join-точки используют
``temporalio.workflow.wait``.

Каждый ``BranchSpec.steps`` — список :class:`ActivityDeclaration` (шаги
ветки, развёрнутые BPMN-импортёром) либо marker-dict
(``{"bpmn_target": target_id}`` — compile-time marker для неподдерживаемой
топологии). На исполнение идут только ActivityDeclaration; marker-dict
игнорируются (ADR-0398).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.dsl.workflow.gateways import BranchSpec, GatewaySpec
from src.backend.dsl.workflow.spec import ActivityDeclaration

__all__ = ("compile_and", "compile_or", "compile_xor")

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
        "expected GatewaySpec or dict"
    )


def _normalize_condition(condition: str) -> str:
    """Привести BPMN-выражение к виду, понятному simpleeval.

    BPMN conditionExpression — это formal-expression: ``${score} >= 700``
    или ``${x>=5}``. simpleeval такого не понимает (имя ``${score}`` не
    определено → eval-error → ветка никогда не выбирается). Поэтому:

    * обёртка ``${...}`` вокруг всего выражения снимается;
    * плейсхолдеры ``${name}`` заменяются на голое имя переменной.

    Args:
        condition: Исходное выражение условия.

    Returns:
        Нормализованное выражение (например ``score >= 700``).

    """
    expr = condition.strip()
    if expr.startswith("${") and expr.endswith("}"):
        expr = expr[2:-1].strip()
    return re.sub(r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}", r"\1", expr)


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
    expression = _normalize_condition(condition)
    try:
        from simpleeval import SimpleEval  # S4 R-V15-4: lazy-import

        return bool(SimpleEval(names=namespace).eval(expression))
    except Exception as exc:
        _logger.warning(
            "gateway condition eval failed: condition=%r expr=%r err=%s; "
            "treating as False",
            condition,
            expression,
            exc,
        )
        return False


async def _run_branch_steps(branch: BranchSpec, ctx: dict[str, Any]) -> Any:
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

    Семантика: ветки стартуют параллельно (task'и создаются в порядке
    объявления), join — ``workflow.wait`` (Temporal-детерминированная
    версия ``asyncio.wait``). Результаты собираются в порядке объявления
    веток, поэтому порядок событий не зависит от того, какая ветка
    завершилась первой.

    ADR-0395: раньше использовался ``asyncio.gather`` — он не запрещён
    sandbox'ом напрямую, но join-семантика (и порядок завершения)
    зависела от event-loop, а ``asyncio.wait`` в sandbox'е Temporal
    рестритктуется явно (temporalio/worker/workflow_sandbox/_restrictions.py).

    Args:
        decl: ActivityDeclaration с ``args['gateway']`` = AND GatewaySpec.
        ctx: Рантайм-контекст workflow.

    Returns:
        Список результатов всех веток (в порядке объявления).

    """
    spec = _resolve_gateway_spec(decl)
    if not spec.branches:
        return []
    tasks = _start_branch_tasks(spec.branches, ctx)
    await _wait_all(tasks)
    return [task.result() for task in tasks]


async def compile_or(decl: ActivityDeclaration, ctx: dict[str, Any]) -> Any:
    """OR (inclusive) gateway: race, cancel remaining on first complete.

    Семантика: каждая ветка запускается как отдельная task;
    ``workflow.wait(FIRST_COMPLETED)`` (Temporal-детерминированная
    версия ``asyncio.wait``) resolves когда **первая** ветка завершается.
    Все pending tasks получают ``task.cancel()`` + await для подавления
    CancelledError-warning.

    Победитель выбирается **детерминированно**: среди завершившихся
    веток берётся первая успешная в порядке объявления (а не «первая
    по времени завершения»). Иначе порядок событий зависел бы от
    скорости внешних систем и ломался бы при replay'е.

    Args:
        decl: ActivityDeclaration с ``args['gateway']`` = OR GatewaySpec.
        ctx: Рантайм-контекст workflow.

    Returns:
        Результат первой завершённой ветки, либо ``None`` если веток нет.

    """
    spec = _resolve_gateway_spec(decl)
    if not spec.branches:
        return None

    tasks = _start_branch_tasks(spec.branches, ctx)
    done, pending = await _wait_first(tasks)

    for task in pending:
        task.cancel()
    # Drain cancelled tasks для подавления "Task was destroyed but it
    # is pending!" warnings; CancelledError ожидаемо и обработано.
    for task in pending:
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Возвращаем первый успешный result в порядке объявления веток;
    # если done-task упал — propagate.
    for task in tasks:
        if task not in done:
            continue
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            raise exc
        return task.result()
    return None


def _start_branch_tasks(
    branches: list[BranchSpec], ctx: dict[str, Any]
) -> list[asyncio.Task[Any]]:
    """Создать task'и для веток gateway в порядке объявления.

    Args:
        branches: Ветки gateway.
        ctx: Рантайм-контекст workflow (shared между ветками).

    Returns:
        Список task'ей (порядок совпадает с порядком веток).

    """
    return [
        get_task_registry().create_task(
            _run_branch_steps(branch, ctx), name=f"gateway-parallel:{idx}"
        )
        for idx, branch in enumerate(branches)
    ]


async def _wait_all(tasks: list[asyncio.Task[Any]]) -> None:
    """Дождаться завершения всех task'ей (детерминированный join-all)."""
    if not tasks:
        return
    await _workflow_wait(tasks)


async def _wait_first(
    tasks: list[asyncio.Task[Any]],
) -> tuple[list[asyncio.Task[Any]], list[asyncio.Task[Any]]]:
    """Дождаться первой завершившейся task'и (детерминированный wait-any)."""
    if not tasks:
        return [], []
    done, pending = await _workflow_wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    return list(done), list(pending)


async def _workflow_wait(
    tasks: list[asyncio.Task[Any]], *, return_when: str = asyncio.ALL_COMPLETED
) -> tuple[list[asyncio.Task[Any]], list[asyncio.Task[Any]]]:
    """Обёртка над ``temporalio.workflow.wait`` (sandbox-safe wait).

    ``asyncio.wait`` рестритктуется Temporal-sandbox'ом
    (``temporalio/worker/workflow_sandbox/_restrictions.py``) как
    недетерминированный API; ``workflow.wait`` — его детерминированная
    замена (список вместо set'а, стабильный порядок ``done``/``pending``).

    Args:
        tasks: Task'и для ожидания.
        return_when: ``ALL_COMPLETED`` (по умолчанию) или ``FIRST_COMPLETED``.

    Returns:
        Кортеж ``(done, pending)`` в порядке объявления task'ей.

    """
    from temporalio import workflow

    result = await workflow.wait(tasks, return_when=return_when)
    return list(result[0]), list(result[1])
