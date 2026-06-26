"""TDD: auth_selector shim — verify_request public API (M12 R4 refactor).

Per S96 W1: src.backend.entrypoints.api.dependencies.auth_selector
это DEPRECATED shim, который re-export'ит canonical реализацию из
``core.auth.auth_selector``. Тест проверяет что shim корректно
экспортирует verify_request (а не определяет его — DRY).

Pattern (D102): facade re-export — единственный допустимый способ
для backward compat shim. Тест должен проверять, что shim содержит
re-export из canonical location, а не определяет полную функцию.

Refs:
- ADR-0207 (capability-checked facades)
- D102 (single-source-of-truth через facade)
- M12 R4 refactor phase
"""
# ruff: noqa: S101
from __future__ import annotations

from pathlib import Path


def _read_source(rel_path: str) -> str:
    """Прочитать содержимое файла относительно project root."""
    project_root = Path(__file__).parent.parent.parent.parent.parent
    return (project_root / rel_path).read_text(encoding="utf-8")


class TestAuthSelectorShim:
    """verify_request в shim — это re-export, не дубликат функции."""

    def test_verify_request_re_exported_from_canonical(self) -> None:
        """verify_request re-exported from core.auth.auth_selector."""
        src = _read_source("src/backend/entrypoints/api/dependencies/auth_selector.py")
        # Должен быть re-export из канонической локации
        assert (
            "from src.backend.core.auth.auth_selector import" in src
        ), "shim должен re-export'ить из core.auth.auth_selector"
        assert "verify_request" in src, "verify_request должен быть в shim"

    def test_verify_request_in_shim_all(self) -> None:
        """verify_request в __all__ backward-compat shim."""
        src = _read_source("src/backend/entrypoints/api/dependencies/auth_selector.py")
        # Shim's __all__ содержит public API для backward compat
        assert (
            '"verify_request"' in src or "'verify_request'" in src
        ), "verify_request должен быть в __all__ для backward compat"

    def test_shim_does_not_redefine_verify_request(self) -> None:
        """В shim НЕ должно быть своего `async def verify_request` — только re-export."""
        src = _read_source("src/backend/entrypoints/api/dependencies/auth_selector.py")
        # Если есть `async def verify_request` — это нарушение DRY (D102)
        assert (
            "async def verify_request(" not in src
        ), "shim НЕ должен определять verify_request — только re-export (DRY/D102)"

    def test_canonical_has_verify_request(self) -> None:
        """Каноническая реализация verify_request существует в core."""
        src = _read_source("src/backend/core/auth/auth_selector.py")
        assert (
            "async def verify_request(" in src
        ), "core.auth.auth_selector должен определять async def verify_request"
