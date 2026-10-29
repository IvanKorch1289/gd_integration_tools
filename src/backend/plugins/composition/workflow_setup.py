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
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.workflow.compiler import CompiledWorkflow, WorkflowCompilerRegistry
from src.backend.dsl.workflow.spec import WorkflowDeclaration
from src.backend.infrastructure.workflow.registry import (
    WorkflowDescriptor,
    workflow_registry,
)

__all__ = (
    "ensure_workflow_declarations_loaded",
    "register_workflow_declarations",
    "start_workflow_runtime",
    "workflow_compiler_registry",
)


_logger = get_logger("workflow.setup")


workflow_compiler_registry: WorkflowCompilerRegistry = WorkflowCompilerRegistry()
"""Глобальный реестр скомпилированных workflow-деклараций."""

_loaded_declarations: list[WorkflowDeclaration] = []
_declarations_loaded: bool = False
_load_lock = threading.Lock()


def _resolve_extensions_dir() -> Path:
    """Определить каталог с workflow-декларациями.

    Порядок разрешения:

    1. env ``EXTENSIONS_DIR`` — явный override (Docker/k8s задают ``/app/extensions``);
    2. ``<repo_root>/extensions`` — корректный путь для локального запуска.

    Раньше дефолтом был жёстко зашитый ``/app/extensions``: при локальном
    запуске вне контейнера каталог не находился, функция молча возвращала
    ``0`` и ни одна workflow-декларация не регистрировалась.

    Returns:
        Путь к каталогу расширений (существование не проверяется).
    """
    from src.backend.core.config.config_loader import repo_root

    configured = os.environ.get("EXTENSIONS_DIR")
    if configured:
        return Path(configured)
    return Path(repo_root()) / "extensions"


def _register_workflow_declarations_from_filesystem() -> int:
    """S124 W1: auto-load ``*.workflow.yaml`` из EXTENSIONS_DIR.

    ADR-0395: в реестр descriptor'ов кладётся **WorkflowDescriptor**
    (а не ``WorkflowDeclaration``). Раньше в реестр попадала сама
    декларация, поэтому admin-trigger читал ``descriptor.input_schema``
    (AttributeError) и MCP-экспорт читал ``descriptor.tags``
    (AttributeError, проглоченный try/except → тихая потеря tool'а).

    Декларации дополнительно **компилируются** в
    :data:`workflow_compiler_registry` — иначе Temporal Worker не
    получал workflow-классы и workflow стартовал, но не исполнялся.

    Идемпотентно: повторный вызов заменяет descriptor (hot-reload),
    а не падает на дубликате.

    Returns:
        Кол-во успешно зарегистрированных workflow-деклараций.
    """
    declarations = ensure_workflow_declarations_loaded()
    return len(declarations)


def ensure_workflow_declarations_loaded(
    *, force: bool = False
) -> list[WorkflowDeclaration]:
    """Загрузить YAML-декларации, зарегистрировать descriptor'ы и скомпилировать.

    Вызывается из двух мест:

    * ``start_workflow_runtime`` (фаза services — после поднятия
      инфраструктуры);
    * ``setup_infra.lifecycle._build_temporal_activities`` (фаза
      infrastructure — раньше неё, иначе Worker поднимался без
      workflow-классов и без activity-list).

    Результат кешируется: повторный вызов без ``force=True`` не
    перечитывает файлы (и не перерегистрирует descriptor'ы).

    Args:
        force: Перезагрузить YAML-файлы даже если они уже загружены
            (hot-reload).

    Returns:
        Список загруженных деклараций (в порядке файлов).

    """
    global _declarations_loaded, _loaded_declarations
    with _load_lock:
        if _declarations_loaded and not force:
            return list(_loaded_declarations)

        declarations = _load_and_register_declarations()
        _loaded_declarations = declarations
        _declarations_loaded = True
        return list(declarations)


def _load_and_register_declarations() -> list[WorkflowDeclaration]:
    """Прочитать YAML-декларации, зарегистрировать descriptor'ы, скомпилировать.

    Returns:
        Список успешно загруженных деклараций.

    """
    from src.backend.dsl.portal import load_workflow_from_yaml

    extensions_dir = _resolve_extensions_dir()
    if not extensions_dir.exists():
        _logger.warning("EXTENSIONS_DIR not found: %s", extensions_dir)
        return []

    declarations: list[WorkflowDeclaration] = []
    for workflow_yaml in sorted(extensions_dir.rglob("*.workflow.yaml")):
        try:
            yaml_text = workflow_yaml.read_text(encoding="utf-8")
            wf = load_workflow_from_yaml(yaml_text)
            rel = workflow_yaml.relative_to(extensions_dir)
            parts = rel.parts  # ('plugin', 'workflows', 'name.workflow.yaml')
            route_id = f"routes/{parts[0]}/{workflow_yaml.stem}"
            _register_descriptor(wf, route_id=route_id)
            _compile_declaration(wf)
            declarations.append(wf)
            _logger.info("workflow.auto_register OK: %s -> %s", wf.name, route_id)
        except Exception as exc:
            _logger.warning(
                "workflow.auto_register FAIL: %s (%s: %s)",
                workflow_yaml,
                type(exc).__name__,
                str(exc)[:200],
            )
    return declarations


def _register_descriptor(decl: WorkflowDeclaration, *, route_id: str) -> None:
    """Зарегистрировать ``WorkflowDescriptor`` для декларации.

    Args:
        decl: Workflow-декларация (YAML).
        route_id: DSL route_id, под которым выполняется workflow.

    """
    descriptor = WorkflowDescriptor(
        name=decl.name,
        description=decl.description or "",
        input_schema=None,
        output_schema=None,
        max_attempts=_descriptor_max_attempts(decl),
        tags=tuple(decl.tags),
    )
    # Replace-semantics (hot-reload): старый descriptor с тем же именем
    # заменяется новым, иначе register() бросил бы ValueError.
    workflow_registry.unregister(decl.name)
    workflow_registry.register(descriptor, route_id=route_id)
    # P0-NEW-3 (cycle 242): register_spec обязателен после register
    # (workflow/registry.py:103). Но spec-реестр принимает только
    # ``WorkflowSpec`` (pg-runner-модель) — YAML-декларации Temporal
    # исполняются worker'ом, а не DSLStepExecutor'ом, поэтому
    # register_spec вызывается лишь для совместимых объектов.
    spec = getattr(decl, "workflow_spec", None)
    if spec is not None:
        workflow_registry.register_spec(route_id, spec)


def _descriptor_max_attempts(decl: WorkflowDeclaration) -> int:
    """Вычислить ``max_attempts`` descriptor'а из retry-политики декларации."""
    policy = decl.default_retry_policy
    if policy is None:
        return 10
    return max(1, int(policy.max_attempts))


def _compile_declaration(decl: WorkflowDeclaration) -> CompiledWorkflow:
    """Скомпилировать декларацию в Temporal workflow-класс.

    Args:
        decl: Workflow-декларация.

    Returns:
        Скомпилированный workflow.

    Raises:
        RuntimeError: Если temporalio SDK не установлен.

    """
    return workflow_compiler_registry.get_or_compile(decl)


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
           (extensions/<name>/workflows/*.workflow.yaml) → workflow_registry
           (descriptor'ы) + workflow_compiler_registry (Temporal-классы).
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
        "workflow.auto_load: %d declarations loaded from EXTENSIONS_DIR", auto_loaded
    )

    state = getattr(app, "state", None)
    if state is not None:
        state.workflow_compiler_registry = workflow_compiler_registry

    _logger.info(
        "Workflow runtime ready: %d declarations compiled",
        len(workflow_compiler_registry.list_names()),
    )
