"""Tests for core/domain/models package (S106 W1 D5 B1).

Verifies:
- All 7 Risk A modules importable from new canonical path.
- Shim re-exports with DeprecationWarning.
- Internal imports use relative ``.base`` (no leaks to old path).
- No regression in User/DslSnapshot/CertRecord tables (metadata reflection).
"""
from __future__ import annotations

import warnings

import pytest


class TestCoreDomainModelsPackage:
    """core/domain/models — canonical package (S106 W1 D5 B1)."""

    def test_all_risk_a_models_importable(self) -> None:
        """All 7 Risk A modules import from new path."""
        from src.backend.core.domain.models import (
            Base,
            BaseModel,
            CertHistory,
            CertRecord,
            DslSnapshot,
            LangMemEpisodic,
            LangMemProcedural,
            OutboxMessage,
            RuleEngineBase,
            RuleEngineRulesetORM,
            User,
            mapper_registry,
            metadata,
            nullable_str,
        )

        assert Base is not None
        assert BaseModel is not None
        assert mapper_registry is not None
        assert metadata is not None
        assert nullable_str is not None
        assert User.__tablename__ == "users"
        assert DslSnapshot.__tablename__ == "dsl_snapshots"
        assert CertRecord.__tablename__ == "certs"
        assert CertHistory.__tablename__ == "cert_history"
        assert OutboxMessage.__tablename__ == "outbox_messages"
        assert RuleEngineRulesetORM.__tablename__ is not None

    def test_init_all_complete(self) -> None:
        """__all__ matches actual exports."""
        from src.backend.core.domain.models import __all__

        assert len(__all__) == 14
        for symbol in (
            "Base",
            "BaseModel",
            "mapper_registry",
            "metadata",
            "nullable_str",
            "CertHistory",
            "CertRecord",
            "DslSnapshot",
            "LangMemEpisodic",
            "LangMemProcedural",
            "OutboxMessage",
            "RuleEngineBase",
            "RuleEngineRulesetORM",
            "User",
        ):
            assert symbol in __all__

    def test_internal_imports_use_relative_base(self) -> None:
        """Moved files import ``.base`` (relative), not absolute old path."""
        from pathlib import Path

        moved_files = (
            "cert.py",
            "dsl_snapshot.py",
            "langmem_models.py",
            "outbox.py",
            "users.py",
        )
        # tests/unit/core/domain/test_X.py → project root = 4 levels up
        project_root = Path(__file__).parent.parent.parent.parent.parent
        models_dir = project_root / "src" / "backend" / "core" / "domain" / "models"
        for name in moved_files:
            path = models_dir / name
            text = path.read_text(encoding="utf-8")
            assert "from .base import" in text, (
                f"{name} should use relative `from .base import`"
            )
            assert "src.backend.infrastructure.database.models.base" not in text, (
                f"{name} still references old infrastructure path"
            )
        # rule_engine.py is fully isolated (uses own RuleEngineBase, not Base)
        rule_engine_text = (models_dir / "rule_engine.py").read_text(encoding="utf-8")
        assert "infrastructure.database.models" not in rule_engine_text

    def test_shim_reexports_with_warning(self) -> None:
        """Old path shims re-export + emit DeprecationWarning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from src.backend.infrastructure.database.models import (  # noqa: F401
                base,
                users,
            )

        deprecations = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecations) >= 2, (
            f"Expected 2 DeprecationWarnings, got {len(deprecations)}"
        )
        # User class re-exported correctly
        assert users.User.__tablename__ == "users"
        # BaseModel re-exported correctly
        assert base.BaseModel.__name__ == "BaseModel"

    def test_shim_warning_message_mentions_new_path(self) -> None:
        """Shim warning explicitly tells consumers where to migrate."""
        import importlib
        import sys

        # Force fresh import to trigger DeprecationWarning
        # (previous shim test cached the module)
        for mod_name in (
            "src.backend.infrastructure.database.models.users",
            "src.backend.infrastructure.database.models",
        ):
            if mod_name in sys.modules:
                del sys.modules[mod_name]

        with warnings.catch_warnings(record=True) as caught:
            warnings.resetwarnings()
            warnings.simplefilter("always")
            importlib.import_module("src.backend.infrastructure.database.models.users")

        msgs = [str(w.message) for w in caught]
        user_warnings = [m for m in msgs if "core.domain.models.users" in m]
        assert len(user_warnings) >= 1, (
            f"Warning should mention new path, got: {msgs}"
        )

    def test_shim_class_identity_with_canonical(self) -> None:
        """Shim classes are the SAME class as canonical (not copy)."""
        from src.backend.core.domain.models import User as CanonicalUser
        from src.backend.infrastructure.database.models import users as shim_users

        assert shim_users.User is CanonicalUser

    def test_metadata_preserved_after_move(self) -> None:
        """SQLAlchemy metadata tables count unchanged after move."""
        from src.backend.core.domain.models import metadata

        # 7 Risk A models register tables in `metadata`
        table_names = set(metadata.tables.keys())
        expected = {"users", "dsl_snapshots", "certs", "cert_history",
                    "outbox_messages"}
        assert expected.issubset(table_names), (
            f"Missing tables: {expected - table_names}"
        )


class TestLayerLinterAfterB1:
    """Linter check — extensions/core_entities/users fixed (41 → 39)."""

    def test_users_domain_models_no_model_violation(self) -> None:
        """extensions/core_entities/users no longer imports Risk A models from old path."""
        from pathlib import Path

        project_root = Path(__file__).parent.parent.parent.parent.parent
        path = (
            project_root
            / "extensions"
            / "core_entities"
            / "users"
            / "domain"
            / "models.py"
        )
        text = path.read_text(encoding="utf-8")
        assert "infrastructure.database.models.users" not in text, (
            "users/domain/models.py should import from core.domain.models"
        )
        assert "core.domain.models.users" in text, (
            "users/domain/models.py must migrate to canonical path"
        )
