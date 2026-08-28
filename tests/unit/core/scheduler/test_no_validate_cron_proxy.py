"""Regression tests для core.scheduler __getattr__ proxy removal (Sprint 39 W1, ADR-0282 Phase B Item 7).

Покрывает:
1. `core.scheduler` НЕ содержит `validate_cron_expression` (__getattr__ block removed).
2. 3 DI symbols preserved: `SchedulerManager`, `get_scheduler_manager`, `scheduler_manager`.
3. Direct infra import works: `infrastructure.scheduler.cron_validator.validate_cron_expression`.
4. Caller migration: `entrypoints/api/v1/endpoints/admin_cron.py:218` → direct infrastructure import.

Per ADR-0282 §3 Phase B (Sprint 39 W1 Item 7): prune 1 entry.
Caller inventory verified 2026-08-27:
- 1 cross-layer caller: `admin_cron.py:218`
- 0 extensions callers
- DSL has own local helper (NOT touching core.scheduler)
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_validate_cron_expression_raises_attribute_error() -> None:
    """`core.scheduler.validate_cron_expression` raises AttributeError.

    Sprint 39 W1: removed `__getattr__` block → `validate_cron_expression`
    no longer accessible через core facade.
    """
    sys.modules.pop("src.backend.core.scheduler", None)

    with pytest.raises(ImportError) as exc_info:
        from src.backend.core.scheduler import validate_cron_expression  # noqa: F401

    assert "validate_cron_expression" in str(exc_info.value).lower() or (
        "cannot import" in str(exc_info.value).lower()
    )


def test_di_symbols_still_importable() -> None:
    """3 DI symbols preserved (NOT touched by Sprint 39 W1)."""
    from src.backend.core.scheduler import (
        SchedulerManager,
        get_scheduler_manager,
        scheduler_manager,
    )

    # All symbols importable (NOT removed)
    assert SchedulerManager is not None
    assert callable(get_scheduler_manager)
    assert scheduler_manager is not None


def test_validate_cron_expression_not_in_dunder_all() -> None:
    """`validate_cron_expression` removed из `__all__`."""
    from src.backend.core import scheduler as core_scheduler

    assert "validate_cron_expression" not in core_scheduler.__all__, (
        "__all__ должен NO LONGER contain validate_cron_expression "
        "(Sprint 39 W1: lazy re-export removed)"
    )


def test_caller_inline_imports_infrastructure() -> None:
    """`entrypoints/admin_cron.py` (1 caller) inline-imports
    `validate_cron_expression` напрямую из infrastructure.

    Sprint 39 W1: removed core.scheduler __getattr__ → caller migrated.
    """
    text = Path("src/backend/entrypoints/api/v1/endpoints/admin_cron.py").read_text(
        encoding="utf-8"
    )
    assert "from src.backend.infrastructure.scheduler.cron_validator import" in text
    assert (
        "from src.backend.core.scheduler import validate_cron_expression" not in text
    ), (
        "admin_cron.py не должна использовать core.scheduler.validate_cron_expression "
        "(Sprint 39 W1: proxy removed)"
    )


class TestGetattrNoLongerDefined:
    """`core.scheduler` НЕ содержит `__getattr__` block (proxy removed)."""

    def test_getattr_raises_for_unknown_symbol(self) -> None:
        """Random symbol import raises AttributeError (no fallback __getattr__)."""
        with pytest.raises(ImportError) as exc_info:
            from src.backend.core.scheduler import unknown_symbol_xyz  # noqa: F401

        # No fallback __getattr__ → "cannot import name" error
        assert "cannot import" in str(exc_info.value).lower()
