"""S92 W3 — File + OrderKind TenantMixin regression tests.

V2 P0 #6 continue: 4/7 models tenant-isolated (Order + User + File + OrderKind).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_file_is_tenant_aware() -> None:
    """File успадковує TenantMixin → _is_tenant_aware повертає True."""
    from src.backend.core.domain.models.files import File
    from src.backend.infrastructure.database.tenant_filter import _is_tenant_aware

    assert _is_tenant_aware(File) is True


@pytest.mark.unit
def test_file_mro_includes_tenant_mixin() -> None:
    """File MRO містить TenantMixin після BaseModel."""
    from src.backend.core.domain.models.files import File

    mro_names = [cls.__name__ for cls in File.__mro__]
    assert "TenantMixin" in mro_names
    assert "BaseModel" in mro_names
    assert mro_names.index("TenantMixin") > mro_names.index("BaseModel")


@pytest.mark.unit
def test_file_tenant_id_column_present() -> None:
    """File має tenant_id mapped_column через TenantMixin."""
    from sqlalchemy import inspect

    from src.backend.core.domain.models.files import File

    mapper = inspect(File)
    columns = {col.key for col in mapper.columns}
    assert "tenant_id" in columns


# ---------------------------------------------------------------------------
# OrderKind
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_orderkind_is_tenant_aware() -> None:
    """OrderKind успадковує TenantMixin → _is_tenant_aware повертає True."""
    from src.backend.core.domain.models.orderkinds import OrderKind
    from src.backend.infrastructure.database.tenant_filter import _is_tenant_aware

    assert _is_tenant_aware(OrderKind) is True


@pytest.mark.unit
def test_orderkind_mro_includes_tenant_mixin() -> None:
    """OrderKind MRO містить TenantMixin після BaseModel."""
    from src.backend.core.domain.models.orderkinds import OrderKind

    mro_names = [cls.__name__ for cls in OrderKind.__mro__]
    assert "TenantMixin" in mro_names
    assert "BaseModel" in mro_names
    assert mro_names.index("TenantMixin") > mro_names.index("BaseModel")


@pytest.mark.unit
def test_orderkind_tenant_id_column_present() -> None:
    """OrderKind має tenant_id mapped_column через TenantMixin."""
    from sqlalchemy import inspect

    from src.backend.core.domain.models.orderkinds import OrderKind

    mapper = inspect(OrderKind)
    columns = {col.key for col in mapper.columns}
    assert "tenant_id" in columns


# ---------------------------------------------------------------------------
# Migration chain integrity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_files_migration_chain() -> None:
    """S92 W1 files migration має правильні revision/down_revision."""
    import importlib.util
    from pathlib import Path

    migration_path = Path(
        "src/backend/infrastructure/database/migrations/versions/"
        "2026_06_12_2100-f8a9b0c1d2e3_files_tenant_id.py"
    )
    spec = importlib.util.spec_from_file_location("s92_w1", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "f8a9b0c1d2e3"
    assert module.down_revision == "e7f8a9b0c1d2"


@pytest.mark.unit
def test_tenant_isolated_models_count() -> None:
    """4/7 моделей мають TenantMixin (Order, User, File, OrderKind)."""
    from src.backend.core.domain.models.files import File
    from src.backend.core.domain.models.orderkinds import OrderKind
    from src.backend.core.domain.models.orders import Order
    from src.backend.core.domain.models.users import User
    from src.backend.infrastructure.database.tenant_filter import _is_tenant_aware

    tenant_aware = [m for m in [Order, User, File, OrderKind] if _is_tenant_aware(m)]
    assert len(tenant_aware) == 4
