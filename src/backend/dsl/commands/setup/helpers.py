from __future__ import annotations

"""S66 W2 — helpers.py part of setup.py decomp.

shared helper (CRUD actions registration).

Functions: _register_crud_actions.
"""

from collections.abc import Callable

from src.backend.dsl.commands.registry import action_handler_registry


def _register_crud_actions(prefix: str, service_getter: Callable) -> None:
    """Регистрирует стандартные CRUD-actions для сервиса на базе BaseService."""
    for method in ("add", "get", "update", "delete"):
        action_handler_registry.register(
            action=f"{prefix}.{method}",
            service_getter=service_getter,
            service_method=method,
        )
