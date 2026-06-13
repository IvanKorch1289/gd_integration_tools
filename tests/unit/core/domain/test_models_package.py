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

        assert len(__all__) == 18
        for symbol in (
            "Base",
            "BaseModel",
            "mapper_registry",
            "metadata",
            "nullable_str",
            "CertHistory",
            "CertRecord",
            "DslSnapshot",
            "File",
            "OrderFile",
            "LangMemEpisodic",
            "LangMemProcedural",
            "OrderKind",
            "Order",
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

    def test_orderkinds_in_canonical_package(self) -> None:
        """S106 W3 (D5 B2a): OrderKind moved to core.domain.models."""
        from src.backend.core.domain.models import OrderKind
        from src.backend.core.domain.models.orderkinds import OrderKind as Direct

        assert OrderKind is Direct
        assert OrderKind.__tablename__ == "orderkinds"
        assert "OrderKind" in __import__(
            "src.backend.core.domain.models", fromlist=["__all__"]
        ).__all__

    def test_orderkinds_shim_re_exports(self) -> None:
        """S106 W3 (D5 B2a): shim re-exports OrderKind with DeprecationWarning."""
        import importlib
        import sys

        for mod_name in (
            "src.backend.infrastructure.database.models.orderkinds",
        ):
            if mod_name in sys.modules:
                del sys.modules[mod_name]

        with warnings.catch_warnings(record=True) as caught:
            warnings.resetwarnings()
            warnings.simplefilter("always")
            importlib.import_module(
                "src.backend.infrastructure.database.models.orderkinds"
            )

        msgs = [str(w.message) for w in caught]
        orderkinds_warnings = [
            m for m in msgs if "core.domain.models.orderkinds" in m
        ]
        assert len(orderkinds_warnings) >= 1

        from src.backend.infrastructure.database.models import orderkinds as shim
        assert shim.OrderKind.__tablename__ == "orderkinds"

    def test_orders_in_canonical_package(self) -> None:
        """S106 W3 (D5 B2b): Order moved to core.domain.models."""
        from src.backend.core.domain.models import Order
        from src.backend.core.domain.models.orders import Order as Direct

        assert Order is Direct
        assert Order.__tablename__ == "orders"
        assert "Order" in __import__(
            "src.backend.core.domain.models", fromlist=["__all__"]
        ).__all__

    def test_orders_orderkind_relationship_after_move(self) -> None:
        """Order ↔ OrderKind bi-directional relationship works post-move."""
        from src.backend.core.domain.models import Order, OrderKind

        # Both moved (orderkinds in W1, orders in W2)
        assert hasattr(Order, "order_kind")
        assert hasattr(OrderKind, "orders")
        # FK constraint name in Order points to orderkinds.id
        fk_columns = [
            col for col in Order.__table__.c
            if col.foreign_keys
        ]
        fk_targets = {list(col.foreign_keys)[0].target_fullname
                      for col in fk_columns}
        assert any("orderkinds" in t for t in fk_targets), (
            f"FK→orderkinds missing: {fk_targets}"
        )

    def test_orders_shim_re_exports(self) -> None:
        """S106 W3 (D5 B2b): shim re-exports Order with DeprecationWarning."""
        import importlib
        import sys

        for mod_name in (
            "src.backend.infrastructure.database.models.orders",
        ):
            if mod_name in sys.modules:
                del sys.modules[mod_name]

        with warnings.catch_warnings(record=True) as caught:
            warnings.resetwarnings()
            warnings.simplefilter("always")
            importlib.import_module(
                "src.backend.infrastructure.database.models.orders"
            )

        msgs = [str(w.message) for w in caught]
        orders_warnings = [
            m for m in msgs if "core.domain.models.orders" in m
        ]
        assert len(orders_warnings) >= 1

        from src.backend.infrastructure.database.models import orders as shim
        assert shim.Order.__tablename__ == "orders"
        assert shim.Order is __import__(
            "src.backend.core.domain.models", fromlist=["Order"]
        ).Order

    def test_files_in_canonical_package(self) -> None:
        """S106 W3 (D5 B2c): File + OrderFile moved to core.domain.models."""
        from src.backend.core.domain.models import File, OrderFile
        from src.backend.core.domain.models.files import (
            File as DirectFile,
            OrderFile as DirectOrderFile,
        )

        assert File is DirectFile
        assert OrderFile is DirectOrderFile
        assert File.__tablename__ == "files"
        assert OrderFile.__tablename__ == "orderfiles"

    def test_files_orderfile_secondary_after_move(self) -> None:
        """Order ↔ File secondary association via OrderFile works post-move."""
        from src.backend.core.domain.models import File, Order, OrderFile

        # secondary association: Order.files via OrderFile.__table__
        assert hasattr(Order, "files")
        assert hasattr(File, "orders")
        assert Order.files.property.secondary is OrderFile.__table__

    def test_files_shim_re_exports(self) -> None:
        """S106 W3 (D5 B2c): shim re-exports File + OrderFile."""
        import importlib
        import sys

        for mod_name in (
            "src.backend.infrastructure.database.models.files",
        ):
            if mod_name in sys.modules:
                del sys.modules[mod_name]

        with warnings.catch_warnings(record=True) as caught:
            warnings.resetwarnings()
            warnings.simplefilter("always")
            importlib.import_module(
                "src.backend.infrastructure.database.models.files"
            )

        msgs = [str(w.message) for w in caught]
        files_warnings = [
            m for m in msgs if "core.domain.models.files" in m
        ]
        assert len(files_warnings) >= 1

        from src.backend.infrastructure.database.models import files as shim
        assert shim.File is __import__(
            "src.backend.core.domain.models", fromlist=["File"]
        ).File
        assert shim.OrderFile is __import__(
            "src.backend.core.domain.models", fromlist=["OrderFile"]
        ).OrderFile


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
