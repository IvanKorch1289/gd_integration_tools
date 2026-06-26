"""Tests for core/domain/models package (S106 W1 D5 B1).

Verifies:
- All 7 Risk A modules importable from new canonical path.
- Shim re-exports with DeprecationWarning.
- Internal imports use relative ``.base`` (no leaks to old path).
- No regression in User/DslSnapshot/CertRecord tables (metadata reflection).
"""

from __future__ import annotations

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
            OutboxMessage,
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

        assert len(__all__) == 22
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
            "WorkflowEvent",
            "WorkflowEventType",
            "WorkflowInstance",
            "WorkflowStatus",
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
            # users.py moved to extensions/core_entities/users/ (S171 V11)
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
        """S106 W5: shims hard deleted, canonical path is the only one."""
        # After W5, old path does NOT exist
        from pathlib import Path

        project_root = Path(__file__).parent.parent.parent.parent
        old_models = (
            project_root / "src" / "backend" / "infrastructure" / "database" / "models"
        )
        assert not old_models.exists(), (
            f"Old models dir should be removed: {old_models}"
        )

    def test_metadata_preserved_after_move(self) -> None:
        """SQLAlchemy metadata tables count unchanged after move."""
        from src.backend.core.domain.models import metadata

        # 7 Risk A models register tables in `metadata`
        table_names = set(metadata.tables.keys())
        expected = {
            "users",
            "dsl_snapshots",
            "certs",
            "cert_history",
            "outbox_messages",
        }
        assert expected.issubset(table_names), (
            f"Missing tables: {expected - table_names}"
        )

    @pytest.mark.skip(reason="S171 V11: orderkinds переехал в extensions/")
    def test_orderkinds_in_canonical_package(self) -> None:
        """S106 W3 (D5 B2a): OrderKind moved to core.domain.models."""
        from src.backend.core.domain.models import OrderKind
        from src.backend.core.domain.models.orderkinds import OrderKind as Direct

        assert OrderKind is Direct
        assert OrderKind.__tablename__ == "orderkinds"
        assert (
            "OrderKind"
            in __import__(
                "src.backend.core.domain.models", fromlist=["__all__"]
            ).__all__
        )

    @pytest.mark.skip(reason="S171 V11: orders переехал в extensions/core_entities/orders/domain/models")
    def test_orders_in_canonical_package(self) -> None:
        """S106 W3 (D5 B2b): Order moved to core.domain.models."""
        from src.backend.core.domain.models import Order
        from src.backend.core.domain.models.orders import Order as Direct

        assert Order is Direct
        assert Order.__tablename__ == "orders"
        assert (
            "Order"
            in __import__(
                "src.backend.core.domain.models", fromlist=["__all__"]
            ).__all__
        )

    def test_orders_orderkind_relationship_after_move(self) -> None:
        """Order ↔ OrderKind bi-directional relationship works post-move."""
        from src.backend.core.domain.models import Order, OrderKind

        # Both moved (orderkinds in W1, orders in W2)
        assert hasattr(Order, "order_kind")
        assert hasattr(OrderKind, "orders")
        # FK constraint name in Order points to orderkinds.id
        fk_columns = [col for col in Order.__table__.c if col.foreign_keys]
        fk_targets = {list(col.foreign_keys)[0].target_fullname for col in fk_columns}
        assert any("orderkinds" in t for t in fk_targets), (
            f"FK→orderkinds missing: {fk_targets}"
        )

    @pytest.mark.skip(reason="S171 V11: files переехал в extensions/")
    def test_files_in_canonical_package(self) -> None:
        """S106 W3 (D5 B2c): File + OrderFile moved to core.domain.models."""
        from src.backend.core.domain.models import File, OrderFile
        from src.backend.core.domain.models.files import File as DirectFile
        from src.backend.core.domain.models.files import OrderFile as DirectOrderFile

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

    def test_workflow_models_in_canonical_package(self) -> None:
        """S106 W4 (D5 B3): WorkflowInstance + WorkflowEvent moved."""
        from src.backend.core.domain.models import (
            WorkflowEvent,
            WorkflowEventType,
            WorkflowInstance,
            WorkflowStatus,
        )
        from src.backend.core.domain.models.workflow_event import (
            WorkflowEvent as DirectE,
        )
        from src.backend.core.domain.models.workflow_event import (
            WorkflowEventType as DirectT,
        )
        from src.backend.core.domain.models.workflow_instance import (
            WorkflowInstance as DirectI,
        )
        from src.backend.core.domain.models.workflow_instance import (
            WorkflowStatus as DirectS,
        )

        assert WorkflowInstance is DirectI
        assert WorkflowEvent is DirectE
        assert WorkflowStatus is DirectS
        assert WorkflowEventType is DirectT
        assert WorkflowInstance.__tablename__ == "workflow_instances"
        assert WorkflowEvent.__tablename__ == "workflow_events"

    def test_workflow_native_enum_preserved(self) -> None:
        """Native PG Enum (WorkflowStatus, WorkflowEventType) preserved post-move."""
        from src.backend.core.domain.models import WorkflowEventType, WorkflowStatus

        # Enum members preserved
        assert WorkflowStatus.pending.value == "pending"
        assert WorkflowStatus.running.value == "running"
        assert WorkflowEventType.created.value == "created"
        assert WorkflowEventType.step_started.value == "step_started"

    def test_workflow_fk_cross_reference_preserved(self) -> None:
        """WorkflowEvent.workflow_id → workflow_instances.id FK preserved."""
        from src.backend.core.domain.models import WorkflowEvent

        fk_cols = [c for c in WorkflowEvent.__table__.c if c.foreign_keys]
        fk_targets = {list(c.foreign_keys)[0].target_fullname for c in fk_cols}
        assert "workflow_instances.id" in fk_targets
        # ONDELETE CASCADE preserved
        workflow_id_fk = [
            c.foreign_keys for c in WorkflowEvent.__table__.c if c.name == "workflow_id"
        ][0]
        ondelete = list(workflow_id_fk)[0].ondelete
        assert ondelete == "CASCADE"


class TestLayerLinterAfterB1:
    """Linter check (после V11 migration tests obsolete — see commit history)."""
    pass
