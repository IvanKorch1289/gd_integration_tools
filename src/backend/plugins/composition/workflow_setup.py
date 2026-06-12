"""Bootstrap durable-workflow runtime (Sprint 4 К3-B).

Содержит:
    * :data:`workflow_compiler_registry` — module-level singleton
      :class:`WorkflowCompilerRegistry`;
    * :func:`register_workflow_declarations` — публичный API для
      плагинов/тестов, batch-регистрирует декларации в singleton'е;
    * :func:`_bootstrap_default_declarations` — default-OFF подключение
      saga-деклараций (``orders_saga`` из
      ``extensions/core_entities/orders/`` + ``payments_saga`` из
      ``extensions/credit_pipeline/``) под
      ``WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED``;
    * :func:`start_workflow_runtime` — entrypoint для lifecycle-цепочки.

Default-OFF feature-flag принцип (V11.1a, V15): ядро не диктует
доменно-специфичные workflow; ``orders_saga``/``payments_saga`` —
демо-декларации, остающиеся в репозитории для smoke/QA.
"""

from __future__ import annotations

from typing import Any, Iterable

from src.backend.core.config.settings import settings
from src.backend.dsl.workflow.compiler import CompiledWorkflow, WorkflowCompilerRegistry
from src.backend.dsl.workflow.spec import WorkflowDeclaration
from src.backend.core.logging import get_logger

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


def _bootstrap_default_declarations() -> list[CompiledWorkflow]:
    """Подключает saga-декларации, если установлен feature-flag.

    Управляется ``WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED`` (default OFF).
    Если флаг не выставлен — функция возвращает пустой список,
    декларации в реестр не попадают.

    Returns:
        Список скомпилированных workflow или ``[]`` при выключённом флаге.
    """

    if not settings.workflow.bootstrap_defaults_enabled:
        _logger.debug(
            "Workflow bootstrap defaults disabled (WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=false)"
        )
        return []

    from extensions.core_entities.orders.workflows.orders_saga import (
        build_orders_saga_workflow,
    )
    from extensions.credit_pipeline.workflows.payments_saga import (
        build_payments_saga_workflow,
    )

    declarations = [build_orders_saga_workflow(), build_payments_saga_workflow()]
    compiled = register_workflow_declarations(declarations)
    _logger.info(
        "Workflow bootstrap defaults registered: %s",
        ", ".join(c.name for c in compiled),
    )
    return compiled


async def start_workflow_runtime(app: Any) -> None:
    """Bootstrap workflow runtime в lifespan приложения.

    Steps:
        1. ``_bootstrap_default_declarations()`` — feature-flag-gated
           регистрация saga-деклараций ДО compile/worker-start.
        2. Размещает singleton compiler-реестра в ``app.state`` для
           использования entry-points (admin API, MCP tools).

    Args:
        app: FastAPI-приложение (с атрибутом ``state``).
    """

    _bootstrap_default_declarations()

    state = getattr(app, "state", None)
    if state is not None:
        state.workflow_compiler_registry = workflow_compiler_registry

    _logger.info(
        "Workflow runtime ready: %d declarations compiled",
        len(workflow_compiler_registry.list_names()),
    )
