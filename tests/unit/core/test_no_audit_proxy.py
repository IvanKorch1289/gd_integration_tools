"""Regression tests для core.audit proxy removal (Sprint 37 W1, ADR-0282 Phase B).

Покрывает:
1. `core.audit` import raises ModuleNotFoundError (proxy removed, NOT stub).
2. `core.audit.facade` subpackage остаётся (real facade, 88 LOC, NOT pruned).
3. Direct infra import works: `infrastructure.audit.event_log.get_audit_log`.
4. Caller migration: 2 entrypoint files (admin_tenants, admin_capabilities)
   импортируют напрямую из infrastructure (NOT через proxy).

Per ADR-0282 §3 Phase B (Sprint 37 W1 Item 4): prune 19 LOC lazy proxy.
Verified: 3 call sites (2 prod entrypoints + 1 test mock unaffected).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_core_audit_get_audit_log_raises_attribute_error() -> None:
    """``core.audit.get_audit_log`` raises AttributeError (proxy removed, namespace package remains).

    Post-fix (Sprint 37 W1): ``core/audit/__init__.py`` deleted.
    ``core/audit/`` becomes PEP 420 namespace package (NO `get_audit_log`).
    Callers MUST import directly из ``infrastructure.audit.event_log``.

    Asserts:
    - ``from src.backend.core.audit import get_audit_log`` raises AttributeError
    - ``core.audit`` остаётся namespace package (facade subdir accessible)
    """
    # Clear any cached imports (defensive — pytest collection order может vary)
    sys.modules.pop("src.backend.core.audit", None)
    sys.modules.pop("src.backend.core.audit.facade", None)

    with pytest.raises(ImportError) as exc_info:
        from src.backend.core.audit import get_audit_log  # noqa: F401

    # Namespace package остаётся, но `get_audit_log` НЕ доступен (proxy removed)
    err_msg = str(exc_info.value).lower()
    assert "get_audit_log" in err_msg or "cannot import" in err_msg, (
        f"Expected ImportError mentioning get_audit_log, got: {exc_info.value}"
    )


def test_core_audit_facade_subpackage_preserved() -> None:
    """``core.audit.facade`` subpackage остаётся (real facade, NOT pruned)."""
    from src.backend.core.audit.facade import emit_audit

    assert callable(emit_audit), "core.audit.facade.emit_audit должен быть callable"


def test_infrastructure_audit_is_canonical_home() -> None:
    """``infrastructure.audit.event_log.get_audit_log`` is canonical."""
    from src.backend.infrastructure.audit.event_log import get_audit_log

    assert callable(get_audit_log)


class TestCallerMigration:
    """Caller migration: 2 entrypoint files → direct infrastructure import."""

    def test_admin_tenants_inline_imports_infrastructure(self) -> None:
        """`entrypoints/admin_tenants.py` (1 caller) inline-imports
        `get_audit_log` напрямую из `infrastructure.audit.event_log`.

        Sprint 37 W1: removed core.audit proxy → caller migrated.
        """
        text = Path(
            "src/backend/entrypoints/api/v1/endpoints/admin_tenants.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.audit.event_log import get_audit_log"
            in text
        )
        assert "from src.backend.core.audit import get_audit_log" not in text, (
            "admin_tenants.py не должна использовать core.audit proxy "
            "(Sprint 37 W1: proxy removed)"
        )

    def test_admin_capabilities_inline_imports_infrastructure(self) -> None:
        """`entrypoints/admin_capabilities.py` (1 caller) inline-imports
        `get_audit_log` напрямую из `infrastructure.audit.event_log`."""
        text = Path(
            "src/backend/entrypoints/api/v1/endpoints/admin_capabilities.py"
        ).read_text(encoding="utf-8")
        assert (
            "from src.backend.infrastructure.audit.event_log import get_audit_log"
            in text
        )
        assert "from src.backend.core.audit import get_audit_log" not in text, (
            "admin_capabilities.py не должна использовать core.audit proxy "
            "(Sprint 37 W1: proxy removed)"
        )


class TestNamespacePackagePreserved:
    """`core/audit/` is now PEP 420 namespace package (no `__init__.py`).

    Subpackage `core.audit.facade` остаётся accessible.
    Direct `get_audit_log` import → ImportError (proxy removed).
    """

    def test_facade_submodule_import_path_intact(self) -> None:
        """`from src.backend.core.audit import facade` still works (namespace pkg)."""
        from src.backend.core.audit import facade

        assert hasattr(facade, "emit_audit"), (
            "core.audit.facade.emit_audit должен быть доступен (subpackage preserved)"
        )

    def test_facade_direct_import_intact(self) -> None:
        """`from src.backend.core.audit.facade import emit_audit` works."""
        from src.backend.core.audit.facade import emit_audit

        assert callable(emit_audit)
