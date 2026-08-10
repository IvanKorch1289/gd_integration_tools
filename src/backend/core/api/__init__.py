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

from __future__ import annotations as annotations

from typing import Any as Any

# Re-export from existing single entry point (src/backend/sdk).
# This facade does NOT replace SDK; it complements it with explicit
# DI providers + AIGateway + SchedulerManager + workflow builders.
from src.backend.sdk import (
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
    "AIGateway",
    # === AI Tool Policy (re-exported) ===
    "AgentToolPolicy",
    # === Errors (re-exported) ===
    "BaseError",
    # === Utilities (re-exported) ===
    "Clock",
    # === DSL Engine (re-exported from src.backend.sdk) ===
    "Exchange",
    "ExtensionRegistrationError",
    "NotebookRegistry",
    "NotebookSpec",
    "Pipeline",
    # === App State decorator (re-exported) ===
    "app_state_singleton",
    "emit_audit_safe",                  # AuditService.safe (never-raises emit)
    "get_auth_facade",                  # AuthFacade (verify + capability)
    "get_cache_facade",                 # UnifiedCacheFacade (get/set/delete/tag)
    "get_clickhouse_client_class",
    "get_elasticsearch_client_class",
    "get_external_db_facade",           # ExternalDBFacade (queries + transactions)
    "get_mongodb_client_class",
    "get_redis_client_class",
    # === Cycle 29 additions: P1-#1 explicit categories ===
    # DI providers (lazy via __getattr__ to avoid import-time deps)
    "get_scheduler_provider",
    # === DI Container (re-exported from src.backend.sdk) ===
    "get_service",
    # === Cycle 31 P2.1 additions: Domain Facades ===
    # Capability-checked facades (via DI providers, lazy).
    # Extensions should prefer these over direct infrastructure imports.
    "get_storage_facade_provider",      # StorageFacade (CRUD + presign + list)
    "is_extension_path",
    "register_factory",
    "register_infra_module",
    # === Jupyter (re-exported) ===
    "run_hub_notebook",
    "unregister_infra_module",
    # NOTE: SchedulerManager and WorkflowBuilder are upper-layer symbols.
    # They live in src.backend.sdk (the permitted composition boundary),
    # NOT in core.api — importing dsl/infrastructure from core violates
    # the layer dependency matrix.
]


# Lazy imports via __getattr__ (cycle 36 S170 pattern) — avoids
# circular deps and keeps import time fast for extension authors
# who only need a few symbols.
def __getattr__(name: str) -> Any:
    """Lazy module-level attribute access for DI providers + classes."""
    # DI providers
    if name == "get_scheduler_provider":
        from src.backend.core.di.providers.scheduler import get_scheduler_provider  # noqa: F401 — re-export

        return get_scheduler_provider
    if name == "get_redis_client_class":
        from src.backend.core.di.providers.infrastructure_locator import (
            get_redis_client_class,
        )

        return get_redis_client_class
    if name == "get_mongodb_client_class":
        from src.backend.core.di.providers.infrastructure_locator import (
            get_mongodb_client_class,
        )

        return get_mongodb_client_class
    if name == "get_elasticsearch_client_class":
        from src.backend.core.di.providers.infrastructure_locator import (
            get_elasticsearch_client_class,
        )

        return get_elasticsearch_client_class
    if name == "get_clickhouse_client_class":
        from src.backend.core.di.providers.infrastructure_locator import (
            get_clickhouse_client_class,
        )

        return get_clickhouse_client_class
    # AIGateway
    if name == "AIGateway":
        from src.backend.core.ai.gateway.gateway import AIGateway  # noqa: F401 — re-export

        return AIGateway
    # === Domain Facades (Cycle 31 P2.1) ===
    if name == "get_storage_facade_provider":
        from src.backend.core.di.providers.storage import get_storage_facade_provider  # noqa: F401 — re-export

        return get_storage_facade_provider
    if name == "get_external_db_facade":
        from src.backend.core.database.external_facade import ExternalDBFacade

        return ExternalDBFacade.get_default
    if name == "get_auth_facade":
        from src.backend.core.auth.facade import get_auth_facade  # noqa: F401 — re-export

        return get_auth_facade
    if name == "get_cache_facade":
        from src.backend.core.di.providers.cache import get_cache_facade  # noqa: F401 — re-export

        return get_cache_facade
    if name == "emit_audit_safe":
        from src.backend.core.audit.facade import emit_audit_safe  # noqa: F401 — re-export

        return emit_audit_safe
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Tab-completion support: include all __all__ + __getattr__ symbols."""
    return sorted([*__all__,
        "get_scheduler_provider",
        "get_redis_client_class",
        "get_mongodb_client_class",
        "get_elasticsearch_client_class",
        "get_clickhouse_client_class",
        "AIGateway",
        "get_storage_facade_provider",
        "get_external_db_facade",
        "get_auth_facade",
        "get_cache_facade",
        "emit_audit_safe",
    ])
