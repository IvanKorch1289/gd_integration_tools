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

S124 W1: добавлена auto-load workflow YAML из EXTENSIONS_DIR
(``extensions/<name>/workflows/*.workflow.yaml``) при compile step.
Ранее workflow-register требовал отдельный hot-load (e.g. через
tests или DSL console). Production-curl trigger ``POST /api/v1/admin/
workflows/trigger/<name>`` видел 400 "There was an error parsing
the body" т.к. ``workflow_registry`` был пустой.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
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


def _register_workflow_declarations_from_filesystem() -> int:
    """S124 W1: auto-load ``*.workflow.yaml`` из EXTENSIONS_DIR.

    Идемпотентно: повторный вызов пере-записывает существующие entries
    (``workflow_registry.register`` идемпотентен по ``name``).

    Returns:
        Кол-во успешно зарегистрированных workflow-деклараций.
    """
    from src.backend.services.workflow import workflow_registry
    from src.backend.services.dsl_portal import load_workflow_from_yaml

    extensions_dir = Path(os.environ.get("EXTENSIONS_DIR", "/app/extensions"))
    if not extensions_dir.exists():
        _logger.warning("EXTENSIONS_DIR not found: %s", extensions_dir)
        return 0

    registered = 0
    for workflow_yaml in sorted(extensions_dir.rglob("*.workflow.yaml")):
        try:
            with open(workflow_yaml) as f:
                yaml_text = f.read()
            wf = load_workflow_from_yaml(yaml_text)
            rel = workflow_yaml.relative_to(extensions_dir)
            parts = rel.parts  # ('plugin', 'workflows', 'name.workflow.yaml')
            route_id = f"routes/{parts[0]}/{workflow_yaml.stem}"
            workflow_registry.register(wf, route_id=route_id)
            registered += 1
            _logger.info(
                "workflow.auto_register OK: %s -> %s", wf.name, route_id,
            )
        except Exception as exc:
            _logger.warning(
                "workflow.auto_register FAIL: %s (%s: %s)",
                workflow_yaml, type(exc).__name__, str(exc)[:200],
            )
    return registered


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
        1. S124 W1: auto-load workflow YAML файлов из EXTENSIONS_DIR
           (extensions/<name>/workflows/*.workflow.yaml) → workflow_registry.
        2. Размещает singleton compiler-реестра в ``app.state`` для
           использования entry-points (admin API, MCP tools).
        3. Плагины регистрируют свои workflow-декларации через
           ``register_workflow_declarations()`` ДО вызова этой функции
           (V11.1a PluginLoader contract).

    D-AUDIT-A8-05 fix (cycle 1): вызов ``_bootstrap_default_declarations``
    удалён — saga-демо модулей больше не существует.

    Args:
        app: FastAPI-приложение (с атрибутом ``state``).

    """
    # S124 W1: auto-load workflow YAML файлов через
    # workflow_compiler_registry + workflow_registry (для admin trigger).
    auto_loaded = _register_workflow_declarations_from_filesystem()
    _logger.info(
        "workflow.auto_load: %d declarations loaded from EXTENSIONS_DIR",
        auto_loaded,
    )

    state = getattr(app, "state", None)
    if state is not None:
        state.workflow_compiler_registry = workflow_compiler_registry

    _logger.info(
        "Workflow runtime ready: %d declarations compiled",
        len(workflow_compiler_registry.list_names()),
    )
