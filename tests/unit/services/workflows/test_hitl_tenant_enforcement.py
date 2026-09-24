"""Regression tests для cross-tenant enforcement в HitlService + store (Option A, ADR-0345).

Per v4 §10 P1 '0 importers + migration window + contract test':
contract tests verify Option A implementation is fail-closed.

Cycle 158+ implementation: добавлен ``tenant_id`` parameter в
Protocol + 2 impls + Service. Per v4 §3 evidence-first, these tests
verify actual behavior (NOT just compile-clean).
"""

from __future__ import annotations

import pytest

from src.backend.core.tenancy import TenantContext, set_tenant
from src.backend.services.workflows.hitl_models import HitlPendingSignal
from src.backend.services.workflows.hitl_service import HitlService
from src.backend.services.workflows.hitl_signal_store import InMemoryHitlSignalStore


def _signal(signal_id: str, tenant: str = "t-1", wf: str = "wf-1") -> HitlPendingSignal:
    return HitlPendingSignal(
        signal_id=signal_id,
        workflow_id=wf,
        tenant_id=tenant,
        signal_name="hitl_approve",
        initiator="user@bank.local",
        title="Approve transfer",
        payload={"amount": 100000},
    )


@pytest.mark.asyncio
class TestHitlTenantEnforcement:
    """Per ADR-0345 Option A: fail-closed per-call tenant check."""

    async def test_get_blocks_cross_tenant_access(self) -> None:
        """Other tenant cannot fetch signal even with valid signal_id.

        Per v4 §10 P1 + ADR-0345: cross-tenant access prevented via
        ``tenant_id`` mismatch returning None.
        """
        store = InMemoryHitlSignalStore()
        svc = HitlService(store=store)
        await svc.register_pending(_signal("s-1", tenant="t-a"))

        # Same-tenant access works (default = no tenant context).
        got = await svc.get("s-1")
        assert got is not None
        assert got.signal_id == "s-1"

        # Cross-tenant access via explicit tenant_id returns None.
        got_cross = await svc.get("s-1", tenant_id="t-b")
        assert got_cross is None, (
            "Cross-tenant access must be blocked (fail-closed)."
        )

    async def test_get_passes_through_when_tenant_matches(self) -> None:
        """Same tenant_id returns signal."""
        store = InMemoryHitlSignalStore()
        svc = HitlService(store=store)
        await svc.register_pending(_signal("s-1", tenant="t-a"))

        got = await svc.get("s-1", tenant_id="t-a")
        assert got is not None
        assert got.signal_id == "s-1"

    async def test_get_uses_current_tenant_when_no_param(self) -> None:
        """If no tenant_id param provided, Service resolves via TenantContext.

        Per ADR-0345 Option A: per-call enforcement. ``set_tenant()``
        populates TenantContext, ``get_tenant_id()`` returns it,
        ``HitlService.get()`` reads it.
        """
        store = InMemoryHitlSignalStore()
        svc = HitlService(store=store)
        await svc.register_pending(_signal("s-1", tenant="t-a"))

        # Set caller's tenant context.
        set_tenant(TenantContext(tenant_id="t-a", plan="pro", region="ru"))
        got = await svc.get("s-1")
        assert got is not None
        assert got.signal_id == "s-1"

        # Switch caller to different tenant — now blocked.
        set_tenant(TenantContext(tenant_id="t-b", plan="pro", region="ru"))
        got_cross = await svc.get("s-1")
        assert got_cross is None, (
            "Cross-tenant access via TenantContext must be blocked."
        )

    async def test_store_get_blocks_cross_tenant_direct(self) -> None:
        """Direct call to ``InMemoryHitlSignalStore.get()`` with tenant_id
        filter returns None for cross-tenant signal.

        Per v4 §3 evidence-first: verify at the lowest layer (Protocol
        implementation), not just service layer.
        """
        store = InMemoryHitlSignalStore()
        await store.put(_signal("s-1", tenant="t-a"))

        # Same-tenant direct store call.
        got = await store.get("s-1", tenant_id="t-a")
        assert got is not None

        # Cross-tenant direct store call.
        got_cross = await store.get("s-1", tenant_id="t-b")
        assert got_cross is None, (
            "Direct store.get() cross-tenant must be blocked."
        )

        # Without tenant_id (legacy): passes through (backwards-compat).
        got_legacy = await store.get("s-1")
        assert got_legacy is not None, (
            "Legacy get() without tenant_id должен return signal "
            "(backwards-compat для существующих callers)."
        )

    async def test_wait_for_blocks_cross_tenant(self) -> None:
        """``wait_for()`` с cross-tenant должен immediately return False
        (без ожидания — fail-closed).
        """
        store = InMemoryHitlSignalStore()
        svc = HitlService(store=store)
        await svc.register_pending(_signal("s-1", tenant="t-a"))

        # Cross-tenant wait_for: should immediately return False.
        result = await svc.wait_for("s-1", timeout=1.0, tenant_id="t-b")
        assert result is False, (
            "Cross-tenant wait_for must NOT wait for event; "
            "return False immediately (fail-closed)."
        )

        # Same-tenant wait_for returns False too (signal not resolved yet).
        result_same = await svc.wait_for("s-1", timeout=0.1, tenant_id="t-a")
        assert result_same is False  # timeout reached, signal not resolved
