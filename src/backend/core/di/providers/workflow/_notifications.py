"""Notifications providers (W9 P2-13 Phase 7).

W9 P2-13 Phase 7 (cycle 153): извлечено из ``core/di/providers/workflow.py``
(602 LOC god-module). Содержит notifications module + workflow_factory_module.

Back-compat: ``core/di/providers/workflow.py`` (file) продолжает re-export
все 4 funcs (workflow_factory_module + notifications_module get_/set_)
через thin ``__init__.py`` shim (см. ADR-0331).

Singleton cache ``_overrides`` is per-domain (NOT shared).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module
from src.backend.core.di.providers.workflow._overrides_store import register

_overrides: dict[str, Any] = {}
register(_overrides)  # aggregate back-compat (providers.workflow._overrides)


# ─── W9 P2-13 Phase 2: workflow_factory_module + notifications_module ──────────


def get_workflow_factory_module_provider() -> Any:
    r"""Возвращает \`workflow.factory\` module alias.

    S87 (legacy): lazy resolve для workflow_subprocess.py.
    R1 fix (S95 PROGRESS_LEDGER): ключ в INFRA_MODULES = ``workflow.factory``,
    а не ``workflow`` (последний отсутствует — 45 ключей без него).
    W9 P2-13 Phase 7: перенесено в workflow/_notifications.py.
    """
    if "workflow_factory_module" in _overrides:
        return _overrides["workflow_factory_module"]
    return resolve_module("workflow.factory")  # R1 fix: ключ + нет .factory suffix


def set_workflow_factory_module_provider(module: Any) -> None:
    """Установить override для ``workflow_factory_module`` provider."""
    _overrides["workflow_factory_module"] = module


def get_notifications_module_provider() -> Any:
    r"""Возвращает \`notifications\` module (notification channels).

    S87 (legacy): lazy resolve для notify/__init__.py.
    W9 P2-13 Phase 7: перенесено в workflow/_notifications.py.
    """
    if "notifications_module" in _overrides:
        return _overrides["notifications_module"]
    module = resolve_module("notifications")
    return module


def set_notifications_module_provider(module: Any) -> None:
    """Установить override для ``notifications_module`` provider."""
    _overrides["notifications_module"] = module
