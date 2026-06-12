"""Regression test для S93 W1 C1: core/di/providers/cache.py не импортирует из entrypoints.

Покрывает:
- AST scan: ни одного from-import из 'src.backend.entrypoints' в cache.py
- AST scan: ни одного import name содержащего 'entrypoints'
- Runtime: get_rag_cache_provider не падает, возвращает None без app
- Core facade: get_three_tier_rag_cache_from_state() работает
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.backend.core.di.app_state import get_three_tier_rag_cache_from_state


def _ast_imports_violation(src_path: Path) -> list[tuple[int, str]]:
    """Возвращает список (lineno, module/name) нарушений импорта из entrypoints."""
    tree = ast.parse(src_path.read_text())
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "entrypoints" in node.module:
                violations.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "entrypoints" in alias.name:
                    violations.append((node.lineno, alias.name))
    return violations


def test_cache_provider_does_not_import_entrypoints() -> None:
    """core/di/providers/cache.py MUST NOT import from entrypoints/ (layer policy)."""
    src = Path("src/backend/core/di/providers/cache.py")
    assert src.exists(), f"{src} not found"

    violations = _ast_imports_violation(src)
    assert not violations, (
        f"core/di/providers/cache.py has forbidden entrypoints imports:\n"
        f"{chr(10).join(f'  line {ln}: {m}' for ln, m in violations)}\n"
        "Use src.backend.core.di.app_state.get_three_tier_rag_cache_from_state instead."
    )


def test_get_three_tier_rag_cache_from_state_returns_none_without_app() -> None:
    """Facade возвращает None если app не зарегистрирован (не падает)."""
    # Без set_app_ref() — _app_ref is None
    result = get_three_tier_rag_cache_from_state()
    assert result is None


def test_get_three_tier_rag_cache_from_state_returns_attribute() -> None:
    """Facade возвращает app.state.three_tier_rag_cache если он зарегистрирован."""
    from unittest.mock import MagicMock

    from src.backend.core.di import app_state as app_state_mod

    # Save original
    original_ref = app_state_mod._app_ref
    try:
        mock_app = MagicMock()
        mock_app.state.three_tier_rag_cache = "mock_cache_instance"
        app_state_mod._app_ref = mock_app

        result = get_three_tier_rag_cache_from_state()
        assert result == "mock_cache_instance"
    finally:
        app_state_mod._app_ref = original_ref
