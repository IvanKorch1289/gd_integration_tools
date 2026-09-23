"""Workflow core providers (W9 P2-13 Phase 7).

W9 P2-13 Phase 7 (cycle 153): извлечено из ``core/di/providers/workflow.py``
(602 LOC god-module). Содержит action bus/dispatcher + scheduler + workflow
storage/DB/ORM models + workflow_backend_factory + workflow_state_repository.

Back-compat: ``core/di/providers/workflow.py`` (file) продолжает re-export
все 13 funcs через thin ``__init__.py`` shim (см. ADR-0331).

Singleton cache ``_overrides`` is per-domain (NOT shared) — каждый submodule
имеет свой override-словарь для изоляции тестов.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module
from src.backend.core.di.providers.workflow._overrides_store import register

_overrides: dict[str, Any] = {}
register(_overrides)  # aggregate back-compat (providers.workflow._overrides)


# ─────────────── Action bus + dispatcher (services.execution) ───────────────


def get_action_bus_service_provider() -> Any:
    """Получить action bus service singleton (для прямых подписок)."""
    if "action_bus_service" in _overrides:
        return _overrides["action_bus_service"]
    module = resolve_module("execution.action_bus")
    return module.get_action_bus_service()


def set_action_bus_service_provider(service: Any) -> None:
    """Установить override для ``action_bus_service`` provider."""
    _overrides["action_bus_service"] = service


def get_action_dispatcher_provider() -> Any:
    """Получить ActionGatewayDispatcher singleton."""
    if "action_dispatcher" in _overrides:
        return _overrides["action_dispatcher"]
    module = resolve_module("execution.action_dispatcher")
    return module.get_action_dispatcher()


def set_action_dispatcher_provider(dispatcher: Any) -> None:
    """Установить override для ``action_dispatcher`` provider."""
    _overrides["action_dispatcher"] = dispatcher


# ─────────────── APScheduler manager ───────────────


def get_scheduler_manager_provider() -> Any:
    """Получить APScheduler manager singleton."""
    if "scheduler_manager" in _overrides:
        return _overrides["scheduler_manager"]
    module = resolve_module("scheduler.manager")
    return module.get_scheduler_manager()


def set_scheduler_manager_provider(manager: Any) -> None:
    """Установить override для ``scheduler_manager`` provider."""
    _overrides["scheduler_manager"] = manager


# ─────────────── Workflow event/state stores (pg_runner_internals) ───────────────


def get_workflow_event_store_provider() -> Any:
    """Получить ``WorkflowEventStore`` class (pg_runner_internals)."""
    if "workflow_event_store" in _overrides:
        return _overrides["workflow_event_store"]
    module = resolve_module("workflow.pg_runner_internals")
    return module.WorkflowEventStore


def set_workflow_event_store_provider(cls: Any) -> None:
    """Установить override для ``workflow_event_store`` provider."""
    _overrides["workflow_event_store"] = cls


def get_workflow_state_store_provider() -> Any:
    """Получить ``WorkflowStateStore`` class (pg_runner_internals)."""
    if "workflow_state_store" in _overrides:
        return _overrides["workflow_state_store"]
    module = resolve_module("workflow.pg_runner_internals")
    return module.WorkflowStateStore


def set_workflow_state_store_provider(cls: Any) -> None:
    """Установить override для ``workflow_state_store`` provider."""
    _overrides["workflow_state_store"] = cls


def get_workflow_state_row_class_provider() -> Any:
    """Получить ``WorkflowStateRow`` class (ORM)."""
    if "workflow_state_row_class" in _overrides:
        return _overrides["workflow_state_row_class"]
    module = resolve_module("workflow.pg_runner_internals")
    return module.WorkflowStateRow


# ─────────────── Workflow DB session + ORM models + enums ───────────────


def get_workflow_main_session_provider() -> Any:
    """Получить main workflow session manager (DB session factory)."""
    if "workflow_main_session" in _overrides:
        return _overrides["workflow_main_session"]
    module = resolve_module("workflow.session_manager")
    return module.get_main_session


def set_workflow_main_session_provider(manager: Any) -> None:
    """Установить override для ``workflow_main_session`` provider."""
    _overrides["workflow_main_session"] = manager


def get_workflow_instance_model_provider() -> Any:
    """Получить ``WorkflowInstance`` ORM model."""
    if "workflow_instance_model" in _overrides:
        return _overrides["workflow_instance_model"]
    module = resolve_module("database.models.workflow_instance")
    return module.WorkflowInstance


def get_workflow_status_enum_provider() -> Any:
    """Получить ``WorkflowStatus`` enum."""
    if "workflow_status_enum" in _overrides:
        return _overrides["workflow_status_enum"]
    module = resolve_module("database.models.workflow_instance")
    return module.WorkflowStatus


# ─── S69 M2-#11 batch 4: workflow backend factory provider ──────────


def get_workflow_backend_factory_provider() -> Any:
    """Получить ``create_workflow_backend`` factory."""
    if "workflow_backend_factory" in _overrides:
        return _overrides["workflow_backend_factory"]
    module = resolve_module("workflow.factory")
    return module.create_workflow_backend


def set_workflow_backend_factory_provider(factory: Any) -> None:
    """Установить override для ``workflow_backend_factory`` provider."""
    _overrides["workflow_backend_factory"] = factory


# ─── S81 M2-#11 batch 16: WorkflowStateRepository provider ──────────


def get_workflow_state_repository_provider() -> Any:
    """Получить ``WorkflowStateRepository`` (saga state repo)."""
    if "workflow_state_repository" in _overrides:
        return _overrides["workflow_state_repository"]
    module = resolve_module("workflow.saga_state")
    return module.WorkflowStateRepository


def set_workflow_state_repository_provider(repo: Any) -> None:
    """Установить override для ``workflow_state_repository`` provider."""
    _overrides["workflow_state_repository"] = repo
