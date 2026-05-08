"""Emitter — динамическая генерация Temporal workflow-классов через ``type()``.

План V16.1 §4 Sprint 4 (К3): :class:`WorkflowDeclaration` →
динамически собранный класс с ``@workflow.defn``, ``@workflow.run``
методом и signal-handler'ами для всех :class:`SignalWaitDeclaration`
шагов в декларации.

Преимущества динамической генерации перед Jinja2-codegen в файл:
    * нет двойного источника правды (декларация vs сгенерированный
      .py-файл);
    * нет race-условий при hot-reload (старый .py не перезаписан, а
      новый класс уже импортируется);
    * deterministic re-emission — двойной вызов :func:`compile_workflow`
      даёт классы с идентичной структурой (полезно для тестов
      replay-determinism).

Опциональный debug-режим (``--debug-emit-source``): источник можно
дампить в ``.cache/workflows/<name>.py`` через :func:`dump_source`,
но это только для просмотра — runtime использует динамический класс.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.backend.dsl.workflow.compiler.step_compilers import dispatch_step_compile
from src.backend.dsl.workflow.spec import SignalWaitDeclaration, WorkflowDeclaration

__all__ = ("CompiledWorkflow", "compile_workflow", "compile_workflows")


_logger = logging.getLogger("workflow.compiler.emitter")


@dataclass(frozen=True, slots=True)
class CompiledWorkflow:
    """Скомпилированный workflow.

    Attrs:
        name: Имя workflow (совпадает с ``decl.name``).
        cls: Динамически созданный класс с ``@workflow.defn``.
        declaration: Исходная декларация (для интроспекции и
            replay-определённости).
        signal_names: Все signal_name из :class:`SignalWaitDeclaration`
            шагов — соответствует зарегистрированным signal-handler'ам.
    """

    name: str
    cls: type
    declaration: WorkflowDeclaration
    signal_names: tuple[str, ...]


def _collect_signal_names(decl: WorkflowDeclaration) -> tuple[str, ...]:
    """Извлечь имена сигналов из всех :class:`SignalWaitDeclaration` шагов."""
    names: list[str] = []
    for step in decl.steps:
        if isinstance(step, SignalWaitDeclaration) and step.signal_name not in names:
            names.append(step.signal_name)
    return tuple(names)


def compile_workflow(decl: WorkflowDeclaration) -> CompiledWorkflow:
    """Скомпилировать :class:`WorkflowDeclaration` в Temporal workflow-класс.

    Args:
        decl: Декларация workflow.

    Returns:
        :class:`CompiledWorkflow` — пара (динамический класс, имя)
        + список signal-имён (для регистрации Worker).

    Raises:
        RuntimeError: Если ``temporalio`` SDK не установлен.
        TypeError: Если в декларации есть step неизвестного типа
          (новый WorkflowStep добавлен без обновления step_compilers).
    """
    try:
        from temporalio import workflow as temporal_workflow
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "temporalio SDK not installed. Install via `uv sync --extra workflow`."
        ) from exc

    signal_names = _collect_signal_names(decl)

    workflow_class_name = _safe_class_name(decl.name)

    async def _run(self: Any, input: dict[str, Any]) -> dict[str, Any]:  # noqa: A002
        """Тело workflow: последовательное выполнение всех шагов."""
        ctx: dict[str, Any] = {
            "_input": input or {},
            "_outputs": {},
            "_signals": getattr(self, "_signals", {}),
            "_default_timeout_s": decl.default_timeout_s,
            "_default_retry_policy": decl.default_retry_policy,
        }
        # Привязываем к self чтобы сигнал-handler мог писать в _signals.
        if not hasattr(self, "_signals"):
            self._signals = ctx["_signals"]

        for step in decl.steps:
            await dispatch_step_compile(step, ctx)

        return {
            "outputs": dict(ctx["_outputs"]),
            "input": dict(ctx["_input"]),
        }

    # Temporal `@workflow.run` запрещает ``<locals>`` в qualname (требует
    # глобально-доступный класс). Перезаписываем qualname так, словно
    # метод определён на модульном классе — это безопасно, так как
    # Temporal worker регистрирует класс по имени в коллекции workflows.
    _run.__qualname__ = f"{workflow_class_name}.run"
    _run.__name__ = "run"

    def _make_init() -> Any:
        def __init__(self: Any) -> None:  # noqa: N807 — dunder name
            self._signals: dict[str, Any] = {}
            self._outputs: dict[str, Any] = {}

        __init__.__qualname__ = f"{workflow_class_name}.__init__"
        return __init__

    # Базовый namespace класса.
    class_namespace: dict[str, Any] = {
        "__doc__": decl.description or f"Workflow {decl.name}",
        "__init__": _make_init(),
    }

    # @workflow.run применяется к методу _run.
    class_namespace["run"] = temporal_workflow.run(_run)

    # Регистрируем signal-handler для каждого SignalWaitDeclaration.signal_name.
    for signal_name in signal_names:
        class_namespace[_signal_attr_name(signal_name)] = _make_signal_handler(
            signal_name, temporal_workflow, owner_class_name=workflow_class_name
        )

    # Динамически создаём класс (Python 3.x type metaclass).
    cls = type(workflow_class_name, (object,), class_namespace)

    # Применяем @workflow.defn(name=decl.name) ПОСЛЕ создания класса.
    cls = temporal_workflow.defn(name=decl.name)(cls)

    return CompiledWorkflow(
        name=decl.name, cls=cls, declaration=decl, signal_names=signal_names
    )


def compile_workflows(
    declarations: list[WorkflowDeclaration],
) -> list[CompiledWorkflow]:
    """Bulk-компиляция списка деклараций.

    Args:
        declarations: Список деклараций.

    Returns:
        Список :class:`CompiledWorkflow` в исходном порядке.
    """
    return [compile_workflow(decl) for decl in declarations]


def _make_signal_handler(
    signal_name: str, temporal_workflow: Any, *, owner_class_name: str
) -> Any:
    """Создать signal-handler для конкретного signal_name.

    Handler сохраняет payload в ``self._signals[signal_name]``;
    workflow run-loop отслеживает наличие ключа через
    ``workflow.wait_condition``.
    """

    async def _handler(self: Any, payload: dict[str, Any] | None = None) -> None:
        self._signals[signal_name] = payload or {}

    attr_name = _signal_attr_name(signal_name)
    _handler.__name__ = attr_name
    _handler.__qualname__ = f"{owner_class_name}.{attr_name}"
    return temporal_workflow.signal(name=signal_name)(_handler)


def _signal_attr_name(signal_name: str) -> str:
    """Преобразовать signal_name в валидный Python attribute name."""
    sanitized = signal_name.replace(".", "_").replace("-", "_")
    return f"_on_signal_{sanitized}"


def _safe_class_name(workflow_name: str) -> str:
    """Преобразовать workflow_name в валидное имя Python-класса."""
    parts = [
        p.capitalize() or "X" for p in workflow_name.replace(".", "_").split("_")
    ]
    candidate = "".join(parts) + "Workflow"
    if not candidate.isidentifier():
        candidate = "DynamicWorkflow"
    return candidate
