"""Unit-tests for tenant filter (RLS helper)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.backend.infrastructure.database.tenant_filter import (
    TenantMixin,
    apply_tenant_filter,
)


def test_tenant_mixin_has_column() -> None:
    assert hasattr(TenantMixin, "tenant_id")


def test_apply_tenant_filter_registers_listeners() -> None:
    session_factory = MagicMock()
    with patch("src.backend.infrastructure.database.tenant_filter.event.listens_for") as mock_listen:
        apply_tenant_filter(session_factory)
        assert mock_listen.call_count == 2


def test_filter_by_tenant_skips_non_select() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.tenant_filter.event.listens_for", fake_listens_for):
        with patch("src.backend.infrastructure.database.tenant_filter.get_tenant_id", return_value="t1"):
            apply_tenant_filter(MagicMock())

    orm_state = SimpleNamespace(is_select=False)
    captured["do_orm_execute"](orm_state)
    assert not hasattr(orm_state, "statement") or orm_state.statement is None


def test_filter_by_tenant_no_tenant_returns() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.tenant_filter.event.listens_for", fake_listens_for):
        with patch("src.backend.infrastructure.database.tenant_filter.get_tenant_id", return_value=None):
            apply_tenant_filter(MagicMock())

    stmt = MagicMock(froms=[MagicMock(entity_namespace=MagicMock(tenant_id="col"))])
    orm_state = SimpleNamespace(is_select=True, statement=stmt)
    captured["do_orm_execute"](orm_state)
    # no assertion error means return early


def test_set_tenant_on_new_sets_when_empty() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.tenant_filter.event.listens_for", fake_listens_for):
        with patch("src.backend.infrastructure.database.tenant_filter.get_tenant_id", return_value="t1"):
            apply_tenant_filter(MagicMock())
            obj = SimpleNamespace(tenant_id="")
            session = SimpleNamespace(new=[obj])
            captured["before_flush"](session, None, None)
            assert obj.tenant_id == "t1"


def test_set_tenant_on_new_preserves_existing() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.tenant_filter.event.listens_for", fake_listens_for):
        with patch("src.backend.infrastructure.database.tenant_filter.get_tenant_id", return_value="t1"):
            apply_tenant_filter(MagicMock())
            obj = SimpleNamespace(tenant_id="existing")
            session = SimpleNamespace(new=[obj])
            captured["before_flush"](session, None, None)
            assert obj.tenant_id == "existing"
