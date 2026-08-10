"""Bootstrap durable-workflow runtime (Sprint 4 К3-B).

Содержит:
    * :data:`workflow_compiler_registry` — module-level singleton
      :class:`WorkflowCompilerRegistry`;
    * :func:`register_workflow_declarations` — публичный API для
      плагинов/тестов, batch-регистрирует декларации в singleton'е;
    * :func:`start_workflow_runtime` — entrypoint для lifecycle-цепочки.

D-AUDIT-A8-05 fix (cycle 1): ``_bootstrap_default_declarations`` удалена.
Ранее функция импортировала ``extensions.core_entities.orders.workflows.orders_saga``
и ``extensions.credit_pipeline.workflows.payments_saga`` — оба модуля удалены
в коммите 9164a59 (S168 W14 "enable all feature flags + remove demos").
Default-OFF флаг WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED маскировал баг;
flip → ModuleNotFoundError на startup.

Domain-agnostic принцип (V11.1a, V15): ядро не диктует доменно-специфичные
workflow — они подключаются через PluginLoader (``extensions/<name>/workflows/``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.workflow.compiler import CompiledWorkflow, WorkflowCompilerRegistry
from src.backend.dsl.workflow.spec import WorkflowDeclaration

__all__ = (
    "register_workflow_declarations",
    "start_workflow_runtime",
    "workflow_compiler_registry",
)


_logger = get_logger("workflow.setup")


workflow_compiler_registry: WorkflowCompilerRegistry = WorkflowCompilerRegistry()
"""Глобальный реестр скомпилированных workflow-деклараций."""


def register_workflow_declarations(
    declarations: Iterable[WorkflowDeclaration],
) -> list[CompiledWorkflow]:
    """Регистрирует декларации в глобальном compiler-реестре.

    Args:
        declarations: Итератор :class:`WorkflowDeclaration`.

    Returns:
        Список свежих :class:`CompiledWorkflow` (бывшие записи с теми
        же именами замещаются — bulk_register идемпотентен по name).
    """

    return workflow_compiler_registry.bulk_register(declarations)


async def start_workflow_runtime(app: Any) -> None:
    """Bootstrap workflow runtime в lifespan приложения.

    Steps:
        1. Размещает singleton compiler-реестра в ``app.state`` для
           использования entry-points (admin API, MCP tools).
        2. Плагины регистрируют свои workflow-декларации через
           ``register_workflow_declarations()`` ДО вызова этой функции
           (V11.1a PluginLoader contract).

    D-AUDIT-A8-05 fix (cycle 1): вызов ``_bootstrap_default_declarations``
    удалён — saga-демо модулей больше не существует.

    Args:
        app: FastAPI-приложение (с атрибутом ``state``).
    """

    state = getattr(app, "state", None)
    if state is not None:
        state.workflow_compiler_registry = workflow_compiler_registry

    _logger.info(
        "Workflow runtime ready: %d declarations compiled",
        len(workflow_compiler_registry.list_names()),
    )
