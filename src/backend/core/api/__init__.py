"""Canonical public API facade for extensions (cycle 29, Master Prompt P1-#1).

Этот модуль — **рекомендуемая** точка входа для ``extensions/`` разработчиков.
Большинство экспортов re-exported из ``src.backend.sdk`` (single entry point
per cycle 36 S170 W14). Этот facade дополняет SDK явными
``__all__``-управляемыми импортами для:

* DI providers (``get_scheduler_provider``, ``get_redis_client_class``)
* AIGateway (canonical LLM entry point, ADR-NEW-19)
* SchedulerManager (production-путь поверх APScheduler/Temporal)
* Workflow builders (DSL fluent API)

Boundary rule (per DEEP_AUDIT_REPORT.md R3.10d):

    extensions import ТОЛЬКО ``src.backend.sdk`` + ``src.backend.core.api``
    (этот модуль). NEVER ``services/*`` or ``infrastructure/*`` directly.

Migration path (P1-#1):
- ``from src.backend.core.X import Y`` (for X in {auth, config, ...}) →
  add to this facade's ``__all__`` → use ``from src.backend.core.api import Y``.
- If Y is in ``src.backend.sdk``, prefer SDK import (less overhead).

History:
- 2026-07-23 cycle 29: created (Master Prompt P1-#1).
- 2026-07-23 cycle 29: lazy imports via ``__getattr__`` (cycle 36 S170
  pattern) to avoid circular dependencies.
"""

from __future__ import annotations

# Re-export from existing single entry point (src/backend/sdk).
# This facade does NOT replace SDK; it complements it with explicit
# DI providers + AIGateway + SchedulerManager + workflow builders.
from src.backend.sdk import (  # noqa: F401
    AgentToolPolicy,
    BaseError,
    Clock,
    Exchange,
    ExtensionRegistrationError,
    NotebookRegistry,
    NotebookSpec,
    Pipeline,
    app_state_singleton,
    get_service,
    is_extension_path,
    register_factory,
    register_infra_module,
    run_hub_notebook,
    unregister_infra_module,
)

__all__ = [
    # === DSL Engine (re-exported from src.backend.sdk) ===
    "Exchange",
    "Pipeline",
    # === DI Container (re-exported from src.backend.sdk) ===
    "get_service",
    "register_factory",
    "register_infra_module",
    "unregister_infra_module",
    "is_extension_path",
    "ExtensionRegistrationError",
    # === App State decorator (re-exported) ===
    "app_state_singleton",
    # === Errors (re-exported) ===
    "BaseError",
    # === Utilities (re-exported) ===
    "Clock",
    # === AI Tool Policy (re-exported) ===
    "AgentToolPolicy",
    # === Jupyter (re-exported) ===
    "run_hub_notebook",
    "NotebookSpec",
    "NotebookRegistry",
    # === Cycle 29 additions: P1-#1 explicit categories ===
    # DI providers (lazy via __getattr__ to avoid import-time deps)
    "get_scheduler_provider",
    "get_redis_client_class",
    "get_mongodb_client_class",
    "get_elasticsearch_client_class",
    "get_clickhouse_client_class",
    # AIGateway (lazy)
    "AIGateway",
    # SchedulerManager (lazy)
    "SchedulerManager",
    # Workflow builders (lazy — re-exported from dsl.workflow.builder)
    "WorkflowBuilder",
]


# Lazy imports via __getattr__ (cycle 36 S170 pattern) — avoids
# circular deps and keeps import time fast for extension authors
# who only need a few symbols.
def __getattr__(name: str):
    """Lazy module-level attribute access for DI providers + classes."""
    # DI providers
    if name == "get_scheduler_provider":
        from src.backend.core.di.providers.scheduler import (
            get_scheduler_provider,
        )

        return get_scheduler_provider
    if name == "get_redis_client_class":
        from src.backend.core.di.providers.infrastructure_facade import (
            get_redis_client_class,
        )

        return get_redis_client_class
    if name == "get_mongodb_client_class":
        from src.backend.core.di.providers.infrastructure_facade import (
            get_mongodb_client_class,
        )

        return get_mongodb_client_class
    if name == "get_elasticsearch_client_class":
        from src.backend.core.di.providers.infrastructure_facade import (
            get_elasticsearch_client_class,
        )

        return get_elasticsearch_client_class
    if name == "get_clickhouse_client_class":
        from src.backend.core.di.providers.infrastructure_facade import (
            get_clickhouse_client_class,
        )

        return get_clickhouse_client_class
    # AIGateway
    if name == "AIGateway":
        from src.backend.core.ai.gateway.gateway import AIGateway

        return AIGateway
    # SchedulerManager
    if name == "SchedulerManager":
        from src.backend.infrastructure.scheduler.scheduler_manager import (
            SchedulerManager,
        )

        return SchedulerManager
    # WorkflowBuilder
    if name == "WorkflowBuilder":
        from src.backend.dsl.workflow.builder import WorkflowBuilder

        return WorkflowBuilder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Tab-completion support: include all __all__ + __getattr__ symbols."""
    return sorted(list(__all__) + [
        "get_scheduler_provider",
        "get_redis_client_class",
        "get_mongodb_client_class",
        "get_elasticsearch_client_class",
        "get_clickhouse_client_class",
        "AIGateway",
        "SchedulerManager",
        "WorkflowBuilder",
    ])
