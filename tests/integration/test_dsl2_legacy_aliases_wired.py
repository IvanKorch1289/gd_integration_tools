"""ITER 16 (Sprint 19): regression test for DSL-2 fix.

DSL-2 (CRITICAL, documented in cycle 242 audit P0_NEW_FIXES_CYCLE_242.md):
legacy_aliases.py referenced 16 actions (orders.list, users.create, ...).
But action_handler_registry only had orders.* and files.* registered
(no _register_users() or _register_orderkinds() in orchestrator).
12 of 16 routes returned 404.

Two-part fix (commit 39a01012):
1. legacy_aliases.py: action names aligned with actual CRUD registration
   (_CRUD_METHODS = ('add', 'get', 'update', 'delete')).
   orders.list → orders.get, orders.create → orders.add (same for users/files/orderkinds).
2. registers_domains.py: added _register_users() and _register_orderkinds().

This test verifies BOTH parts:
1. All 16 legacy alias actions are registered in the registry after
   register_action_handlers() is called.
2. legacy_aliases._ALIASES uses action names that match the registry.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.commands.registry import action_handler_registry
from src.backend.dsl.commands.setup import register_action_handlers
from src.backend.entrypoints.api.generator import legacy_aliases


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Clear registry between tests for isolation."""
    action_handler_registry._handlers.clear()  # type: ignore[attr-defined]


def test_all_16_legacy_aliases_registered() -> None:
    """DSL-2 fix: all 16 actions referenced by legacy_aliases ARE in registry.

    Before fix: only 4 of 16 actions existed (orders.* + files.*).
    After fix: 16/16 actions registered via _register_orders/_files/users/orderkinds.
    """
    register_action_handlers()
    actions = set(action_handler_registry.list_actions())

    for _path, params, _methods in legacy_aliases._ALIASES:
        action = params["action"]
        assert action in actions, (
            f"DSL-2 fix regressed: {action} not in action_handler_registry. "
            f"Check _register_users() and _register_orderkinds() in "
            f"src/backend/dsl/commands/setup/orchestrator.py"
        )


def test_legacy_aliases_use_crud_method_names() -> None:
    """DSL-2 fix: action names align with _CRUD_METHODS = ('add', 'get', ...).

    Pre-fix: legacy_aliases used 'orders.list', 'orders.create' (REST verbs).
    Post-fix: uses 'orders.get', 'orders.add' (CRUD method names).
    """
    # Get all action names from legacy_aliases
    alias_actions = {params["action"] for _path, params, _methods in legacy_aliases._ALIASES}

    # None of them should be 'list' or 'create' (these were the broken names)
    assert "list" not in alias_actions, "legacy_aliases still uses 'list' verbs (DSL-2 regression)"
    assert "create" not in alias_actions, "legacy_aliases still uses 'create' verbs (DSL-2 regression)"

    # They should use 'get' and 'add' (CRUD method names)
    for action in alias_actions:
        method = action.rsplit(".", 1)[-1]
        assert method in {"get", "add", "update", "delete"}, (
            f"legacy_aliases action {action} uses non-CRUD method '{method}'"
        )


def test_register_users_helper_exists_and_is_wired() -> None:
    """DSL-2 fix: _register_users() exists and is called by orchestrator."""
    from src.backend.dsl.commands.setup import registers_domains
    from src.backend.dsl.commands.setup import orchestrator

    assert hasattr(registers_domains, "_register_users"), (
        "_register_users() missing from registers_domains"
    )
    assert hasattr(orchestrator, "_register_users"), (
        "_register_users() not imported in orchestrator"
    )
    # Verify it's called in register_action_handlers()
    import inspect

    source = inspect.getsource(orchestrator.register_action_handlers)
    assert "_register_users()" in source, (
        "register_action_handlers does not call _register_users()"
    )


def test_register_orderkinds_helper_exists_and_is_wired() -> None:
    """DSL-2 fix: _register_orderkinds() exists and is called by orchestrator."""
    from src.backend.dsl.commands.setup import registers_domains
    from src.backend.dsl.commands.setup import orchestrator

    assert hasattr(registers_domains, "_register_orderkinds"), (
        "_register_orderkinds() missing from registers_domains"
    )
    assert hasattr(orchestrator, "_register_orderkinds"), (
        "_register_orderkinds() not imported in orchestrator"
    )
    import inspect

    source = inspect.getsource(orchestrator.register_action_handlers)
    assert "_register_orderkinds()" in source, (
        "register_action_handlers does not call _register_orderkinds()"
    )


def test_legacy_aliases_paths_match_existing_conventions() -> None:
    """DSL-2 fix: 16 paths use 4 resources × 4 verbs (consistent)."""
    paths = [path for path, _params, _methods in legacy_aliases._ALIASES]
    # Each resource has 4 paths (all, create, update/<id>, delete/<id>)
    for resource in ("orders", "users", "files", "orderkinds"):
        resource_paths = [p for p in paths if p.startswith(f"/{resource}/")]
        assert len(resource_paths) == 4, (
            f"Resource {resource} has {len(resource_paths)} paths (expected 4)"
        )
