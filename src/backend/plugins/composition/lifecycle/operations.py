"""Типизированный lifecycle: операции с criticality, timeout и зависимостями.

Контекст (аудит 2026-10-01, HEAD ``3b509542e``)
----------------------------------------------
До этого файла операции старта/остановки описывались кортежами:

* ``STARTUP_PHASES: tuple[Phase, ...]``, где ``Phase = Callable[[FastAPI], Awaitable[None]]``
  (``lifecycle/startup_phases/__init__.py:27,30``);
* ``starting_operations / ending_operations: list[OperationItem]``,
  ``OperationItem = tuple[str, Callable, Callable[[], bool] | None]``
  (``setup_infra/lifecycle.py:37-39,346,385``).

Ни одна из структур не несла ``criticality``, ``timeout`` или ``dependencies``,
из-за чего:

1. startup выполнялся строго последовательно, без учёта зависимостей
   (``lifecycle/startup.py:224-225``);
2. падение на N-й операции **не вызывало откат**: ``lifespan.py:102-105``
   выполнял ``run_shutdown`` только при ``startup_completed=True``;
3. падение одной завершающей операции пропускало остальные
   (``setup_infra/lifecycle.py:117-123`` делает ``raise`` внутри цикла);
4. не было структурированного отчёта о том, что стартовало, что деградировало
   и что было пропущено.

Модуль вводит :class:`LifecycleOperation` и :class:`LifecycleRunner` с
заявленной семантикой: топологический старт, reverse-order rollback,
идемпотентный shutdown, изоляцию ошибок shutdown и отдельное состояние
optional-деградации.

Политика criticality
--------------------
``REQUIRED``
    Падение останавливает startup: выполняется откат уже стартовавших операций
    в обратном порядке, после чего исключение пробрасывается наружу.
``OPTIONAL``
    Падение не останавливает startup: операция помечается как деградировавшая,
    её ``stop`` **не** вызывается при откате (она не считается стартовавшей),
    а факт деградации попадает в структурированный отчёт.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = (
    "Criticality",
    "LifecycleOperation",
    "LifecycleOutcome",
    "LifecycleReport",
    "LifecycleRunner",
    "LifecycleState",
)

_logger = logging.getLogger(__name__)

#: Значение ``timeout`` по умолчанию, если операция его не задала.
DEFAULT_TIMEOUT_SECONDS = 30.0


class Criticality(enum.StrEnum):
    """Критичность операции для успешного старта приложения."""

    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


class LifecycleState(enum.StrEnum):
    """Итоговое состояние операции после startup."""

    STARTED = "STARTED"
    SKIPPED_DISABLED = "SKIPPED_DISABLED"
    DEGRADED = "DEGRADED"
    ROLLED_BACK = "ROLLED_BACK"
    NOT_STARTED = "NOT_STARTED"


@dataclass(frozen=True, slots=True)
class LifecycleOperation:
    """Одна типизированная операция жизненного цикла.

    Attributes:
        name: Уникальное имя операции (используется в отчёте и rollback).
        phase: Имя startup-фазы, которой принадлежит операция
            (``observability`` / ``infrastructure`` / ``services``).
        start: Корутина запуска. Может быть синхронной функцией —
            тогда результат awaits при вызове.
        stop: Корутина остановки. ``None`` — откатывать нечего.
        enabled: Предикат включения. ``None`` — операция включена всегда.
        criticality: ``REQUIRED`` останавливает startup, ``OPTIONAL`` деградирует.
        timeout: Таймаут запуска в секундах.
        dependencies: Имена операций, которые должны завершиться раньше.

    """

    name: str
    phase: str
    start: Callable[[], Awaitable[Any] | Any]
    stop: Callable[[], Awaitable[Any] | Any] | None = None
    enabled: Callable[[], bool] | bool | None = None
    criticality: Criticality = Criticality.REQUIRED
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    dependencies: tuple[str, ...] = ()

    def is_enabled(self) -> bool:
        """Проверить предикат включения операции.

        Returns:
            ``True``, если операцию следует выполнять.

        """
        if self.enabled is None:
            return True
        if isinstance(self.enabled, bool):
            return self.enabled
        return bool(self.enabled())


@dataclass(slots=True)
class LifecycleOutcome:
    """Результат выполнения одной операции.

    Attributes:
        name: Имя операции.
        phase: Фаза операции.
        state: Итоговое состояние.
        criticality: Критичность операции.
        duration_s: Длительность запуска в секундах.
        error: Текст ошибки, если операция завершилась неуспешно.

    """

    name: str
    phase: str
    state: LifecycleState = LifecycleState.NOT_STARTED
    criticality: Criticality = Criticality.REQUIRED
    duration_s: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Представить результат словарём (для структурированного отчёта).

        Returns:
            JSON-совместимое представление результата.

        """
        return {
            "name": self.name,
            "phase": self.phase,
            "state": str(self.state),
            "criticality": str(self.criticality),
            "duration_s": round(self.duration_s, 4),
            "error": self.error,
        }


@dataclass(slots=True)
class LifecycleReport:
    """Структурированный отчёт о выполнении lifecycle.

    Attributes:
        outcomes: Результаты по каждой операции в порядке плана.
        rollback_performed: Выполнялся ли откат.
        shutdown_errors: Ошибки, накопленные при shutdown.

    """

    outcomes: list[LifecycleOutcome] = field(default_factory=list)
    rollback_performed: bool = False
    shutdown_errors: list[str] = field(default_factory=list)

    def by_state(self, state: LifecycleState) -> list[LifecycleOutcome]:
        """Выбрать результаты с указанным состоянием.

        Args:
            state: Искомое состояние.

        Returns:
            Список результатов.

        """
        return [o for o in self.outcomes if o.state is state]

    @property
    def degraded(self) -> list[LifecycleOutcome]:
        """Операции, деградировавшие по criticality=OPTIONAL."""
        return self.by_state(LifecycleState.DEGRADED)

    @property
    def required_all_started(self) -> bool:
        """Все ли REQUIRED-операции стартовали успешно."""
        return not self.by_state(LifecycleState.DEGRADED) or all(
            o.criticality is Criticality.OPTIONAL
            for o in self.by_state(LifecycleState.DEGRADED)
        )

    def to_dict(self) -> dict[str, Any]:
        """Представить отчёт словарём.

        Returns:
            JSON-совместимое представление отчёта.

        """
        return {
            "operations": [o.to_dict() for o in self.outcomes],
            "rollback_performed": self.rollback_performed,
            "shutdown_errors": list(self.shutdown_errors),
            "degraded": [o.name for o in self.degraded],
            "required_all_started": self.required_all_started,
        }


class LifecycleRunner:
    """Исполнитель lifecycle-операций.

    Гарантии:

    * старт в топологическом порядке с учётом ``dependencies``;
    * таймаут на каждую операцию (``timeout``);
    * падение REQUIRED-операции → откат уже стартовавших в **обратном**
      порядке и пробрасывание исключения;
    * падение OPTIONAL-операции → деградация без остановки startup;
    * shutdown идемпотентен и изолирован: ошибка одной ``stop`` не мешает
      остальным.

    """

    def __init__(self, operations: Iterable[LifecycleOperation]) -> None:
        """Инициализировать runner.

        Args:
            operations: Операции жизненного цикла.

        """
        self._operations: list[LifecycleOperation] = list(operations)
        self._started: list[LifecycleOperation] = []
        # Операции, чей start был ПРЕДПРИНЯТ (N-4). Откат обязан
        # останавливать и частично поднятые, иначе ресурсы утекают.
        self._attempted: list[LifecycleOperation] = []
        self._outcomes: dict[str, LifecycleOutcome] = {}
        self._shutdown_done = False
        self._rollback_performed = False
        self._shutdown_errors: list[str] = []

    @property
    def plan(self) -> list[LifecycleOperation]:
        """Топологический план выполнения операций.

        Returns:
            Операции в порядке, удовлетворяющем ``dependencies``.

        Raises:
            ValueError: если в зависимостях есть цикл или неизвестное имя.

        """
        by_name = {op.name: op for op in self._operations}
        if len(by_name) != len(self._operations):
            duplicates = {
                name
                for name in by_name
                if [o.name for o in self._operations].count(name) > 1
            }
            raise ValueError(f"Дубликаты имён lifecycle-операций: {sorted(duplicates)}")

        for op in self._operations:
            unknown = [d for d in op.dependencies if d not in by_name]
            if unknown:
                raise ValueError(
                    f"Операция {op.name!r} ссылается на неизвестные зависимости: {unknown}"
                )

        ordered: list[LifecycleOperation] = []
        placed: set[str] = set()
        remaining = list(self._operations)
        while remaining:
            progressed = False
            for op in list(remaining):
                if all(dep in placed for dep in op.dependencies):
                    ordered.append(op)
                    placed.add(op.name)
                    remaining.remove(op)
                    progressed = True
            if not progressed:
                raise ValueError(
                    "Цикл в зависимостях lifecycle-операций: "
                    f"{[op.name for op in remaining]}"
                )
        return ordered

    def _record(
        self,
        op: LifecycleOperation,
        state: LifecycleState,
        *,
        duration_s: float = 0.0,
        error: str = "",
    ) -> LifecycleOutcome:
        """Записать результат операции.

        Args:
            op: Операция.
            state: Итоговое состояние.
            duration_s: Длительность запуска.
            error: Текст ошибки.

        Returns:
            Записанный результат.

        """
        outcome = LifecycleOutcome(
            name=op.name,
            phase=op.phase,
            state=state,
            criticality=op.criticality,
            duration_s=duration_s,
            error=error,
        )
        self._outcomes[op.name] = outcome
        return outcome

    async def start_all(self) -> LifecycleReport:
        """Выполнить startup всех операций.

        Returns:
            Структурированный отчёт.

        Raises:
            BaseException: исключение от REQUIRED-операции после отката.

        """
        plan = self.plan
        for op in plan:
            self._outcomes.setdefault(
                op.name,
                LifecycleOutcome(
                    name=op.name, phase=op.phase, criticality=op.criticality
                ),
            )

        for op in plan:
            if not op.is_enabled():
                self._record(op, LifecycleState.SKIPPED_DISABLED)
                continue

            started_at = time.perf_counter()
            # Fail-closed (независимый re-аудит 2026-10-01, N-4): операция
            # попадает в _attempted ДО попытки старта, а не после успеха. Раньше
            # операция, упавшая после частичного подъёма ресурсов (или по
            # TimeoutError), в откат не попадала вовсе — её stop() не
            # вызывался, и пул/клиент/фоновые задачи утекали. _started при этом
            # сохраняет прежнюю семантику «успешно поднято», поэтому обычный
            # shutdown не начинает дёргать stop() у не стартовавших операций.
            self._attempted.append(op)
            try:
                async with asyncio.timeout(op.timeout):
                    result = op.start()
                    if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                        await result
            except TimeoutError:
                duration = time.perf_counter() - started_at
                await self._handle_failure(
                    op,
                    f"TimeoutError: операция не завершилась за {op.timeout}s",
                    duration,
                )
                continue
            except Exception as exc:
                duration = time.perf_counter() - started_at
                await self._handle_failure(op, f"{type(exc).__name__}: {exc}", duration)
                continue

            duration = time.perf_counter() - started_at
            self._record(op, LifecycleState.STARTED, duration_s=duration)
            self._started.append(op)

        return self.report()

    async def _handle_failure(
        self, op: LifecycleOperation, error: str, duration: float
    ) -> None:
        """Обработать падение операции согласно её criticality.

        Args:
            op: Упавшая операция.
            error: Текст ошибки.
            duration: Длительность до падения.

        Raises:
            Exception: для REQUIRED-операции — после отката.

        """
        if op.criticality is Criticality.OPTIONAL:
            self._record(op, LifecycleState.DEGRADED, duration_s=duration, error=error)
            _logger.warning(
                "optional lifecycle operation degraded: op=%s error=%s", op.name, error
            )
            return

        self._record(op, LifecycleState.DEGRADED, duration_s=duration, error=error)
        _logger.error(
            "required lifecycle operation failed: op=%s error=%s — выполняется откат",
            op.name,
            error,
        )
        await self.rollback()
        raise LifecycleStartupError(op.name, error) from None

    async def rollback(self) -> list[str]:
        """Откатить уже стартовавшие операции в обратном порядке.

        Returns:
            Список имён операций, для которых ``stop`` завершился ошибкой.

        """
        self._rollback_performed = True
        failures: list[str] = []
        # N-4: откат идёт по _attempted, а не по _started — частично
        # поднятая операция обязана получить stop().
        for op in reversed(self._attempted):
            if op.stop is None:
                continue
            try:
                result = op.stop()
                if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                    await result
            except Exception as exc:  # noqa: BLE001 — изоляция отката
                failures.append(f"{op.name}: {type(exc).__name__}: {exc}")
                _logger.error(
                    "rollback stop failed (продолжаем откат): op=%s error=%s",
                    op.name,
                    exc,
                )
                continue
            self._record(op, LifecycleState.ROLLED_BACK)
        self._started.clear()
        return failures

    async def shutdown(self) -> list[str]:
        """Остановить стартовавшие операции в обратном порядке.

        Идемпотентен: повторный вызов ничего не делает. Ошибка одной операции
        не мешает остановке остальных.

        Returns:
            Список ошибок остановки.

        """
        if self._shutdown_done:
            return list(self._shutdown_errors)
        self._shutdown_done = True

        for op in reversed(list(self._started)):
            if op.stop is None:
                continue
            try:
                result = op.stop()
                if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                    await result
            except Exception as exc:  # noqa: BLE001 — shutdown изолирован
                self._shutdown_errors.append(f"{op.name}: {type(exc).__name__}: {exc}")
                _logger.error(
                    "lifecycle stop failed (продолжаем shutdown): op=%s error=%s",
                    op.name,
                    exc,
                )
        self._started.clear()
        return list(self._shutdown_errors)

    def report(self) -> LifecycleReport:
        """Собрать структурированный отчёт.

        Returns:
            Отчёт с результатами в порядке плана.

        """
        outcomes: list[LifecycleOutcome] = []
        for op in self._operations:
            outcomes.append(
                self._outcomes.get(
                    op.name,
                    LifecycleOutcome(
                        name=op.name, phase=op.phase, criticality=op.criticality
                    ),
                )
            )
        return LifecycleReport(
            outcomes=outcomes,
            rollback_performed=self._rollback_performed,
            shutdown_errors=list(self._shutdown_errors),
        )


class LifecycleStartupError(RuntimeError):
    """Ошибка старта REQUIRED-операции (после выполненного отката).

    Attributes:
        operation: Имя упавшей операции.

    """

    def __init__(self, operation: str, detail: str) -> None:
        """Инициализировать ошибку.

        Args:
            operation: Имя упавшей операции.
            detail: Текст исходной ошибки.

        """
        self.operation = operation
        super().__init__(
            f"Lifecycle startup failed at required operation {operation!r}: {detail}"
        )


def build_operations(
    items: Sequence[tuple[str, str, Callable[[], Any], Callable[[], Any] | None]],
    *,
    enabled: dict[str, Callable[[], bool] | None] | None = None,
    criticality: dict[str, Criticality] | None = None,
    timeout: dict[str, float] | None = None,
    dependencies: dict[str, tuple[str, ...]] | None = None,
) -> list[LifecycleOperation]:
    """Собрать :class:`LifecycleOperation` из плоских кортежей.

    Существует для плавной миграции существующих списков операций без
    дублирования кода: вызывающий код передаёт те же кортежи, а метаданные
    (criticality/timeout/dependencies) задаёт словарями.

    Args:
        items: Кортежи ``(name, phase, start, stop)``.
        enabled: Предикаты включения по имени операции.
        criticality: Критичность по имени операции.
        timeout: Таймауты по имени операции.
        dependencies: Зависимости по имени операции.

    Returns:
        Список типизированных операций.

    """
    enabled = enabled or {}
    criticality = criticality or {}
    timeout = timeout or {}
    dependencies = dependencies or {}
    return [
        LifecycleOperation(
            name=name,
            phase=phase,
            start=start,
            stop=stop,
            enabled=enabled.get(name),
            criticality=criticality.get(name, Criticality.REQUIRED),
            timeout=timeout.get(name, DEFAULT_TIMEOUT_SECONDS),
            dependencies=dependencies.get(name, ()),
        )
        for name, phase, start, stop in items
    ]
