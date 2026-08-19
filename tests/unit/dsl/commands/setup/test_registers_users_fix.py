"""Regression-блокировка для NEW-8 fix: _register_users() function.

Pre-NEW-8: в ``src/backend/dsl/commands/setup/registers_domains.py`` были
только ``_register_orders()`` и ``_register_files()``. UserService
существовал, но actions не регистрировались.
``POST /api/v1/auto/users.add`` → 404 "Not Found" (action not in registry).

NEW-8 fix (2026-08-13):
1. Добавлена ``_register_users()`` функция в registers_domains.py
2. Добавлен импорт + вызов ``_register_users()`` в orchestrator.py

Тесты:

1. ``_register_users()`` существует в registers_domains module.
2. Orchestrator вызывает ``_register_users()`` при bootstrap.
3. ``_register_users()`` импортирует ``get_user_service`` из extensions.
4. ``_register_users()`` вызывает ``_register_crud_actions("users", svc)``.
"""

from __future__ import annotations


def test_register_users_function_exists() -> None:
    """``_register_users()`` определена в registers_domains (NEW-8)."""
    from src.backend.dsl.commands.setup import registers_domains

    assert hasattr(registers_domains, "_register_users"), (
        "NEW-8 fix regressed: _register_users missing from registers_domains"
    )
    assert callable(registers_domains._register_users)


def test_register_users_imports_get_user_service() -> None:
    """``_register_users()`` функция references ``get_user_service`` (NEW-8)."""
    import inspect

    from src.backend.dsl.commands.setup import registers_domains

    source = inspect.getsource(registers_domains._register_users)
    assert "get_user_service" in source, (
        "NEW-8 fix regressed: _register_users doesn't import get_user_service"
    )
    assert "extensions.core_entities.users.services.users" in source, (
        "_register_users should import from extensions.core_entities.users"
    )


def test_register_users_calls_crud_actions() -> None:
    """``_register_users()`` вызывает ``_register_crud_actions("users", ...)``."""
    import inspect

    from src.backend.dsl.commands.setup import registers_domains

    source = inspect.getsource(registers_domains._register_users)
    assert "_register_crud_actions" in source, (
        "NEW-8 fix regressed: _register_users doesn't call _register_crud_actions"
    )
    assert '"users"' in source or "'users'" in source, (
        "_register_users should target 'users' entity"
    )


def test_orchestrator_registers_users() -> None:
    """Orchestrator bootstrap вызывает _register_users (NEW-8 wiring)."""
    import inspect

    from src.backend.dsl.commands.setup import orchestrator

    source = inspect.getsource(orchestrator)
    assert "_register_users" in source, (
        "NEW-8 fix regressed: orchestrator doesn't call _register_users"
    )
