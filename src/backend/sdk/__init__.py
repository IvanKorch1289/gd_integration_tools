"""Extension SDK — stable public API surface for GD Integration Tools plugins.

Этот модуль — **единственный** публичный API для разработчиков расширений.
Все классы и функции, не перечисленные в ``__all__``, являются внутренними
и могут измениться без предупреждения.

Рекомендуемый импорт::

    from src.backend.sdk import Exchange, Pipeline, get_service, register_factory

Extension points:
    - Pipeline / Exchange — DSL engine primitives
    - get_service / register_factory — runtime DI container
    - register_infra_module — infrastructure-module DI (S172 M3 ARC-006)
    - app_state_singleton — singleton decorator for FastAPI app state
    - BaseError — корневой класс ошибок приложения
    - Clock — монотонные часы для метрик и timeouts
"""

from __future__ import annotations

from src.backend.core.clock import Clock
from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.errors import BaseError
from src.backend.core.svcs_registry import get_service, register_factory
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline

__all__ = [
    # DSL Engine
    "Exchange",
    "Pipeline",
    # DI Container (runtime services)
    "get_service",
    "register_factory",
    # DI infrastructure-module registry (S172 M3 ARC-006)
    "register_infra_module",
    "unregister_infra_module",
    "ExtensionRegistrationError",
    "is_extension_path",
    # App State decorator
    "app_state_singleton",
    # Errors
    "BaseError",
    # Utilities
    "Clock",
    # Jupyter Hub (S170 NEW)
    "run_hub_notebook",
    "NotebookSpec",
    "NotebookRegistry",
    # AI Tool Policy (S170 P0-7)
    "AgentToolPolicy",
]

# Публичные типы для type-checking
__all__ += ["ConnectorRegistry", "get_provider", "register_provider"]


# Эти импорты могут вызывать циклические зависимости, поэтому import-поздние.
def __getattr__(name: str):
    if name == "ConnectorRegistry":
        from src.backend.infrastructure.registry import ConnectorRegistry

        return ConnectorRegistry
    if name == "get_provider":
        from src.backend.core.providers_registry import get_provider

        return get_provider
    if name == "register_provider":
        from src.backend.core.providers_registry import register_provider

        return register_provider
    if name == "run_hub_notebook":
        from src.backend.services.jupyter.hub_run_orchestrator import run_hub_notebook

        return run_hub_notebook
    if name == "NotebookSpec":
        from src.backend.services.jupyter.notebook_registry import NotebookSpec

        return NotebookSpec
    if name == "NotebookRegistry":
        from src.backend.services.jupyter.notebook_registry import NotebookRegistry

        return NotebookRegistry
    if name == "AgentToolPolicy":
        from src.backend.ai.policy import AgentToolPolicy

        return AgentToolPolicy
    # S172 M3 ARC-006 — Extension DI infrastructure-module registry.
    if name == "register_infra_module":
        from src.backend.core.di.module_registry import register_extension_module

        return register_extension_module
    if name == "unregister_infra_module":
        from src.backend.core.di.module_registry import unregister_extension_module

        return unregister_extension_module
    if name == "ExtensionRegistrationError":
        from src.backend.core.di.module_registry import ExtensionRegistrationError

        return ExtensionRegistrationError
    if name == "is_extension_path":
        from src.backend.core.di.module_registry import is_extension_path

        return is_extension_path
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
