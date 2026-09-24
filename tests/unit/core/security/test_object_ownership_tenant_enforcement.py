"""Regression tests для cross-tenant enforcement в ``require_object_ownership``
decorator (Option A, ADR-0345 fix #7).

Per v4 §10 P1 '0 importers + migration window + contract test':
contract tests verify fail-closed behavior в ``_verify_ownership``.

Cycle 158+ implementation (v5 prompt directive): decorator
``require_object_ownership`` теперь принимает optional ``session_factory``
+ ``explicit_tenant_id`` параметры. При наличии обоих — full fail-closed
verification через DB load + tenant_id compare. Без них — legacy stub
behavior (backwards-compat).

Per v4 §3 evidence-first: тесты verify actual behavior, не just compile.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.core.errors import AuthorizationError, NotFoundError
from src.backend.core.security.object_ownership import (
    _verify_ownership,
)


def _make_model_class(name: str = "TestModel") -> type:
    """Build minimal SQLAlchemy-like model for tests."""

    class _MockModel:
        # Marker attribute to indicate SQLAlchemy-style ``get`` is supported.
        # ``_verify_ownership`` checks ``getattr(model, 'get', None) is not None``.
        get = lambda self, *args, **kwargs: None  # placeholder

    _MockModel.__name__ = name
    return _MockModel


def _make_resource(resource_id: int | str, tenant: str | None) -> object:
    """Build resource-like object with id + tenant_id."""
    res = MagicMock()
    res.id = resource_id
    res.tenant_id = tenant
    return res


@pytest.mark.asyncio
class TestRequireObjectOwnership:
    """Per ADR-0345 Option A: fail-closed per-call tenant check."""

    async def test_missing_id_param_raises_value_error(self) -> None:
        """``id_param=None`` raises ValueError (always, even legacy stub)."""
        model = _make_model_class()
        with pytest.raises(ValueError, match="missing required param"):
            await _verify_ownership(
                resource_model=model,
                id_param="missing",
                tenant_field="tenant_id",
                kwargs={},
                raise_on_mismatch=True,
            )

    async def test_legacy_stub_path_without_session_factory(self) -> None:
        """Без session_factory — legacy stub (logs only, no fail-closed).

        Per v4 §10 P1 backwards-compat: existing callers без session
        infrastructure continue working (no breaking change).
        """
        model = _make_model_class()
        # Should NOT raise — only logs.
        await _verify_ownership(
            resource_model=model,
            id_param="id",
            tenant_field="tenant_id",
            kwargs={"id": 42},
            raise_on_mismatch=True,
            # session_factory=None (legacy path).
        )

    async def test_legacy_stub_path_without_explicit_tenant(self) -> None:
        """Без explicit_tenant_id — legacy stub (no fail-closed)."""
        model = _make_model_class()
        await _verify_ownership(
            resource_model=model,
            id_param="id",
            tenant_field="tenant_id",
            kwargs={"id": 42},
            raise_on_mismatch=True,
            session_factory=lambda: MagicMock(),
            # explicit_tenant_id=None (legacy path).
        )

    async def test_fail_closed_blocks_cross_tenant(self) -> None:
        """Same tenant_id mismatch → raise AuthorizationError (fail-closed).

        Per ADR-0345 Option A: cross-tenant access blocked.
        """
        model = _make_model_class()
        session = MagicMock()
        session.get.return_value = _make_resource(
            resource_id=42, tenant="t-a"
        )

        with pytest.raises(AuthorizationError, match="Tenant mismatch"):
            await _verify_ownership(
                resource_model=model,
                id_param="id",
                tenant_field="tenant_id",
                kwargs={"id": 42},
                raise_on_mismatch=True,
                session_factory=lambda: session,
                explicit_tenant_id="t-b",  # Caller from t-b.
            )

    async def test_fail_closed_allows_same_tenant(self) -> None:
        """Same tenant_id → pass (no exception)."""
        model = _make_model_class()
        session = MagicMock()
        session.get.return_value = _make_resource(
            resource_id=42, tenant="t-a"
        )

        # Should NOT raise.
        await _verify_ownership(
            resource_model=model,
            id_param="id",
            tenant_field="tenant_id",
            kwargs={"id": 42},
            raise_on_mismatch=True,
            session_factory=lambda: session,
            explicit_tenant_id="t-a",
        )

    async def test_fail_closed_resource_not_found_raises_not_found_error(self) -> None:
        """Resource missing → raise NotFoundError (fail-closed)."""
        model = _make_model_class()
        session = MagicMock()
        session.get.return_value = None  # Not found.

        with pytest.raises(NotFoundError, match="not found"):
            await _verify_ownership(
                resource_model=model,
                id_param="id",
                tenant_field="tenant_id",
                kwargs={"id": 42},
                raise_on_mismatch=True,
                session_factory=lambda: session,
                explicit_tenant_id="t-a",
            )

    async def test_fail_closed_db_error_raises_authorization_error(self) -> None:
        """DB lookup exception → fail-closed raise AuthorizationError.

        Per audit + ADR-0345: unexpected errors → fail-closed (not silent).
        """
        model = _make_model_class()
        session = MagicMock()
        session.get.side_effect = RuntimeError("connection lost")

        with pytest.raises(AuthorizationError, match="Failed to load"):
            await _verify_ownership(
                resource_model=model,
                id_param="id",
                tenant_field="tenant_id",
                kwargs={"id": 42},
                raise_on_mismatch=True,
                session_factory=lambda: session,
                explicit_tenant_id="t-a",
            )

    async def test_fail_closed_falls_back_to_query_when_no_get(self) -> None:
        """Если model не имеет ``get()`` method, fallback to ``query().filter_by().first()``."""
        model = MagicMock()
        # No ``get`` attribute — fallback to query.
        del model.get
        query = MagicMock()
        query.filter_by.return_value.first.return_value = _make_resource(
            resource_id=42, tenant="t-a"
        )
        session = MagicMock()
        session.query.return_value = query

        # Should NOT raise.
        await _verify_ownership(
            resource_model=model,
            id_param="id",
            tenant_field="tenant_id",
            kwargs={"id": 42},
            raise_on_mismatch=True,
            session_factory=lambda: session,
            explicit_tenant_id="t-a",
        )

    async def test_raise_on_mismatch_false_returns_silently_on_mismatch(self) -> None:
        """``raise_on_mismatch=False`` → no raise, caller handles via return."""
        model = _make_model_class()
        session = MagicMock()
        session.get.return_value = _make_resource(
            resource_id=42, tenant="t-a"
        )

        # Should NOT raise even with mismatched tenants.
        await _verify_ownership(
            resource_model=model,
            id_param="id",
            tenant_field="tenant_id",
            kwargs={"id": 42},
            raise_on_mismatch=False,  # caller handles
            session_factory=lambda: session,
            explicit_tenant_id="t-b",
        )
