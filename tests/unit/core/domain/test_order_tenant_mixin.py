"""S89 W4 — regression tests для Order + TenantMixin integration.

S89 W4 (V2 P0 #6): verify that:
1. Order успадковує TenantMixin (MRO check)
2. Order.tenant_id field is present with correct definition
3. apply_tenant_filter (S88 W2) повертає _is_tenant_aware=True для Order
4. Order model імпортується без помилок
5. OrderFile (FK to Order) не ламається
6. OrderKind (FK to Order) не ламається
"""

from __future__ import annotations

from src.backend.core.domain.models.orders import Order
from src.backend.infrastructure.database.tenant_filter import (
    TenantMixin,
    _is_tenant_aware,
)


def test_order_inherits_tenant_mixin() -> None:
    """Order(BaseModel, TenantMixin) — TenantMixin в MRO."""
    assert TenantMixin in Order.__mro__, (
        f"Expected TenantMixin in Order.__mro__, got: {Order.__mro__}"
    )


def test_order_has_tenant_id_field() -> None:
    """Order має tenant_id column (успадковано від TenantMixin)."""
    assert hasattr(Order, "tenant_id"), "Order should have tenant_id attribute"


def test_order_tenant_id_column_spec() -> None:
    """Order.tenant_id: VARCHAR(64) NOT NULL DEFAULT 'default' index=True."""
    col = Order.tenant_id
    # String type
    assert "VARCHAR" in str(col.type) or "String" in str(type(col.type).__name__), (
        f"Expected VARCHAR/String, got: {col.type}"
    )
    # NOT NULL
    assert col.nullable is False, f"Expected NOT NULL, got nullable={col.nullable}"
    # DEFAULT 'default'
    assert col.default is not None, "Expected default value"
    # Index
    assert col.index is True, f"Expected indexed, got index={col.index}"


def test_is_tenant_aware_for_order() -> None:
    """_is_tenant_aware(Order) — True (has tenant_id via TenantMixin)."""
    assert _is_tenant_aware(Order) is True


def test_order_imports_without_error() -> None:
    """Order module import не ламається після S89 W2+W3 changes."""
    # Якщо цей test запускається, імпорт вже відбувся
    assert Order.__tablename__ == "orders"
    assert Order.__name__ == "Order"


def test_order_mro_order() -> None:
    """MRO: Order → BaseModel → TenantMixin → object."""
    mro = Order.__mro__
    # Order перший
    assert mro[0] is Order
    # TenantMixin має бути десь в MRO
    assert TenantMixin in mro
    # object має бути останнім
    assert mro[-1] is object


def test_order_existing_fields_preserved() -> None:
    """S89 W2+W3 не видалив жодне з існуючих полів Order."""
    expected_fields = {
        "order_kind_id",
        "pledge_gd_id",
        "pledge_cadastral_number",
        "is_active",
        "is_send_to_gd",
        "is_send_request_to_skb",
        "errors",
        "object_uuid",
        "response_data",
        "email_for_answer",
        "tenant_id",  # New in S89 W2
    }
    # Check that all expected fields are in __table__.columns
    actual_columns = set(Order.__table__.columns.keys())
    missing = expected_fields - actual_columns
    assert not missing, f"Missing fields: {missing}; actual: {actual_columns}"


def test_order_relationships_preserved() -> None:
    """Order.relationships — order_kind, files — збережені після S89."""
    # Import related models для SQLAlchemy mapper initialization
    from src.backend.core.domain.models.files import OrderFile
    from src.backend.core.domain.models.orderkinds import OrderKind

    # SQLAlchemy relationships
    rels = Order.__mapper__.relationships
    rel_names = {r.key for r in rels}
    assert "order_kind" in rel_names
    assert "files" in rel_names
    # Verify related classes loaded
    assert OrderKind.__name__ == "OrderKind"
    assert OrderFile.__name__ == "OrderFile"
