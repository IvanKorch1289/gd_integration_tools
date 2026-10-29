"""ADR-0396 — Saga-компенсации в pg-runner-пути (кластер C, wave 19).

До wave 19 компенсации в pg-runner НЕ исполнялись: ``kind="compensate"``
был no-op в dispatch'е, а runner при ``FAILED`` только записывал статус —
откат терялся (дефект ревью «[high] Компенсации в pg-runner-пути НЕ
исполняются»).

Семантика выровнена с Temporal-путём
(:mod:`src.backend.dsl.workflow.compiler.step_compilers.flow`):

* компенсации исполняются в **reverse-порядке** относительно уже
  выполненных forward-шагов (упавший шаг не компенсируется);
* маппинг forward→compensate: явный ``WorkflowSpec.compensate_map``
  (имя forward-шага → имя compensate-шага), иначе позиционный
  (i-й compensate-шаг ↔ i-й forward-шаг);
* ``strict_compensate`` — ошибки компенсаций chain'ятся с исходной
  ошибкой forward-шага (:class:`CompensationError`).

Модуль не знает про БД и event-log: он строит план, исполняет цепочку
через переданный callback и возвращает/поднимает результат. Запись в
event-log делает executor (``executor/__init__.py``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.infrastructure.workflow.executor.sequential_mixin import _run_processor

if TYPE_CHECKING:
    from src.backend.infrastructure.workflow.executor.state import (
        WorkflowSpec,
        WorkflowStep,
    )

__all__ = (
    "CompensationAction",
    "CompensationError",
    "CompensationOutcome",
    "build_compensation_plan",
    "execute_compensation",
    "execute_compensation_step",
)

_logger = get_logger("workflow.executor.compensating")

#: Callback исполнения одного compensate-шага.
CompensationExecutor = Callable[["WorkflowStep"], Awaitable[Any]]


class CompensationError(RuntimeError):
    """Ошибка компенсации с цепочкой исключений.

    Семантика повторяет Temporal-путь (``raise original from
    comp_errors[-1]``), но сохраняет полный список ошибок:

    Attributes:
        original: Исходная ошибка forward-шага, из-за которого запущена
            компенсация.
        errors: Все ошибки компенсаций (в порядке исполнения).

    """

    def __init__(
        self,
        message: str,
        *,
        original: BaseException,
        errors: Sequence[BaseException],
    ) -> None:
        super().__init__(message)
        self.original = original
        self.errors = tuple(errors)


@dataclass(frozen=True, slots=True)
class CompensationAction:
    """Одно действие компенсации — откат конкретного forward-шага.

    Attributes:
        forward_name: Имя forward-шага, который откатывается.
        step: Compile-шаг с rollback-действием (``kind="compensate"``).

    """

    forward_name: str
    step: WorkflowStep


@dataclass(frozen=True, slots=True)
class CompensationOutcome:
    """Результат исполнения цепочки компенсаций.

    Attributes:
        executed: Имена успешно исполненных compensate-шагов.
        errors: Ошибки компенсаций (пусто — все откаты прошли).

    """

    executed: tuple[str, ...] = ()
    errors: tuple[BaseException, ...] = ()

    @property
    def failed(self) -> bool:
        """Есть ли ошибки компенсации."""
        return bool(self.errors)


def build_compensation_plan(
    spec: WorkflowSpec,
    *,
    completed_names: Sequence[str],
) -> list[CompensationAction]:
    """Построить план компенсаций для уже выполненных forward-шагов.

    Args:
        spec: Workflow spec: forward-шаги (``kind != "compensate"``) и
            rollback-шаги (``kind == "compensate"``).
        completed_names: Имена forward-шагов, которые уже выполнены
            (упавший шаг в список не входит — он не компенсируется).

    Returns:
        Список :class:`CompensationAction` в порядке исполнения:
        последний выполненный forward-шаг компенсируется первым.

    """
    forward_steps = [s for s in spec.steps if s.kind != "compensate"]
    compensate_steps = [s for s in spec.steps if s.kind == "compensate"]
    compensate_by_name = {s.name: s for s in compensate_steps}
    completed = set(completed_names)

    pairs: list[tuple[str, WorkflowStep]] = []
    if spec.compensate_map:
        for forward in forward_steps:
            if forward.name not in completed:
                continue
            compensate_name = spec.compensate_map.get(forward.name)
            if compensate_name is None:
                continue
            step = compensate_by_name.get(compensate_name)
            if step is None:
                _logger.warning(
                    "compensate_map: шаг %r не найден (forward=%r) — пропущен",
                    compensate_name,
                    forward.name,
                )
                continue
            pairs.append((forward.name, step))
    else:
        # Позиционный fallback (совпадает с Temporal-путём):
        # i-й compensate-шаг откатывает i-й forward-шаг.
        for index, forward in enumerate(forward_steps):
            if forward.name not in completed or index >= len(compensate_steps):
                continue
            pairs.append((forward.name, compensate_steps[index]))

    return [
        CompensationAction(forward_name=name, step=step)
        for name, step in reversed(pairs)
    ]


async def execute_compensation_step(
    step: WorkflowStep,
    *,
    body: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    """Исполнить processors компенсационного шага (rollback-действие).

    Args:
        step: Compensate-шаг (``kind="compensate"``) с processors'ами.
        body: Тело exchange, передаваемое в processors.
        timeout_s: Таймаут на один processor (как у forward-шага).

    Returns:
        Тело exchange после отката.

    Raises:
        Exception: Любая ошибка processor'а — пробрасывается вызывающему
            (собирается в цепочку исключений компенсации).

    """
    for proc in step.processors:
        body = await _run_processor(proc, body, timeout_s)
    return body


async def execute_compensation(
    *,
    plan: Sequence[CompensationAction],
    execute: CompensationExecutor,
    original_error: BaseException,
    strict: bool = True,
) -> CompensationOutcome:
    """Исполнить цепочку компенсаций.

    Args:
        plan: План компенсаций (уже в reverse-порядке).
        execute: Callback исполнения одного compensate-шага.
        original_error: Исходная ошибка forward-шага — попадает в
            цепочку исключений.
        strict: True → при ошибках компенсаций поднимается
            :class:`CompensationError` (chain исключений); False →
            ошибки возвращаются в :class:`CompensationOutcome`.

    Returns:
        :class:`CompensationOutcome` — исполненные шаги + ошибки.

    Raises:
        CompensationError: при ``strict=True`` и хотя бы одной ошибке
            компенсации (``__cause__`` — последняя ошибка компенсации).

    """
    executed: list[str] = []
    errors: list[BaseException] = []
    for action in plan:
        try:
            await execute(action.step)
        except Exception as exc:  # noqa: BLE001 — граница saga-шага
            errors.append(exc)
            _logger.error(
                "compensation failed for forward step %s (%s): %s",
                action.forward_name,
                action.step.name,
                exc,
            )
            continue
        executed.append(action.step.name)
        _logger.info(
            "compensation executed: forward=%s compensate=%s",
            action.forward_name,
            action.step.name,
        )

    if errors and strict:
        raise CompensationError(
            f"compensation failed for {len(errors)} step(s): "
            + ", ".join(type(err).__name__ for err in errors),
            original=original_error,
            errors=errors,
        ) from errors[-1]
    return CompensationOutcome(executed=tuple(executed), errors=tuple(errors))
