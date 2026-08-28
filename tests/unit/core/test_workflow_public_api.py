"""Regression tests для core.workflow facade cleanup (Sprint 35 W1, ADR-0282 Phase B).

Покрывает:
1. `core.workflow` no longer re-exports `create_workflow_backend` (lazy
   __getattr__ block удалён).
2. Core-only symbols still importable: `WorkflowBackend`, `WorkflowHandle`,
   `WorkflowResult`, `WorkflowStatus`, `FakeWorkflowBackend`.
3. Caller migration: `admin_workflow_versioning.py` imports
   `create_workflow_backend` напрямую из `infrastructure.workflow.factory`.

Per ADR-0282 §3 Phase B: simple prune workflow-фасады (1 caller, no
layer-crossing risk — entrypoints → infrastructure is allowed per ALLOWED
matrix). Verification: allowlist count 60 → 59.
"""

from __future__ import annotations

import importlib

import pytest


class TestCoreWorkflowPublicAPI:
    """core.workflow остаётся Protocol + Pydantic + Fake (NO factory)."""

    def test_core_only_symbols_still_importable(self) -> None:
        """Core symbols (Protocol + Pydantic + Fake) остаются в public API."""
        from src.backend.core.workflow import (
            FakeWorkflowBackend,
            WorkflowBackend,
            WorkflowHandle,
            WorkflowResult,
            WorkflowStatus,
        )

        # Все symbols должны быть импортируемыми (НЕ deleted)
        assert WorkflowBackend is not None
        assert WorkflowHandle is not None
        assert WorkflowResult is not None
        assert WorkflowStatus is not None
        assert FakeWorkflowBackend is not None

    def test_create_workflow_backend_no_longer_in_facade(self) -> None:
        """`create_workflow_backend` removed из core.workflow (Sprint 35 W1).

        Lazy `__getattr__` block удалён. Caller должен использовать direct
        import из `infrastructure.workflow.factory`.
        """
        from src.backend.core import workflow as core_workflow

        # AttributeError expected (no longer in __all__ or __getattr__)
        with pytest.raises(AttributeError) as exc_info:
            core_workflow.create_workflow_backend  # type: ignore[attr-defined]

        assert "create_workflow_backend" in str(exc_info.value)
        assert "module" in str(exc_info.value).lower()

    def test_create_workflow_backend_no_longer_in_dunder_all(self) -> None:
        """`create_workflow_backend` removed из `__all__` (был listed)."""
        from src.backend.core import workflow as core_workflow

        assert "create_workflow_backend" not in core_workflow.__all__, (
            "__all__ должен NO LONGER contain create_workflow_backend "
            "(Sprint 35 W1: удалён lazy re-export)"
        )


class TestCallerMigration:
    """Verify caller inline-import из infrastructure (single caller pattern)."""

    def test_admin_workflow_versioning_inline_imports_factory(self) -> None:
        """`admin_workflow_versioning.py` (1 caller) inline-imports
        `create_workflow_backend` напрямую из `infrastructure.workflow.factory`.

        Sprint 35 W1: removed core.workflow facade → caller мигрирован.
        """
        text = (
            importlib.resources.files("src.backend.entrypoints.api.v1.endpoints")
            .joinpath("admin_workflow_versioning.py")
            .read_text(encoding="utf-8")
        )

        # Caller импортирует из infrastructure напрямую
        assert (
            "from src.backend.infrastructure.workflow.factory import create_workflow_backend"
            in text
        ), (
            "admin_workflow_versioning.py должна inline-import из "
            "infrastructure.workflow.factory (Sprint 35 W1 migration)"
        )

        # Caller NO LONGER использует core.workflow facade для factory
        assert (
            "from src.backend.core.workflow import create_workflow_backend" not in text
        ), (
            "admin_workflow_versioning.py не должна использовать core.workflow.create_workflow_backend "
            "(Sprint 35 W1: facade removed)"
        )


class TestInfrastructureFactoryIsCanonical:
    """`infrastructure.workflow.factory.create_workflow_backend` is canonical."""

    def test_factory_callable(self) -> None:
        """Factory `create_workflow_backend` должна быть callable."""
        from src.backend.infrastructure.workflow.factory import create_workflow_backend

        assert callable(create_workflow_backend), (
            "create_workflow_backend должна быть callable factory"
        )
