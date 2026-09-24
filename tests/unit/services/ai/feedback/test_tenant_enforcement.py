"""Regression tests для cross-tenant enforcement в AIFeedbackRepository (Option A, ADR-0345).

Per v4 §10 P1 '0 importers + migration window + contract test':
contract tests verify fail-closed behavior в AIFeedbackService.

Cycle 158+ implementation: добавлен ``tenant_id`` parameter в
``FeedbackRepository`` Protocol + ``InMemoryFeedbackRepository`` impl +
``AIFeedbackService.get()``. Per v4 §3 evidence-first, эти tests
verify actual behavior (NOT just compile-clean).
"""

from __future__ import annotations

import pytest

from src.backend.core.models.feedback import AIFeedbackDoc
from src.backend.core.tenancy import TenantContext, set_tenant
from src.backend.services.ai.feedback import AIFeedbackService
from src.backend.services.ai.feedback.repository import InMemoryFeedbackRepository


def _make_doc(
    doc_id: str = "d-1",
    tenant: str | None = "t-a",
    agent: str = "agent-1",
) -> AIFeedbackDoc:
    """Build test AIFeedbackDoc with tenant_id в metadata."""
    metadata: dict = {"agent_id": agent}
    if tenant is not None:
        metadata["tenant_id"] = tenant
    return AIFeedbackDoc(
        id=doc_id,
        query="test",
        response="response",
        agent_id=agent,
        metadata=metadata,
    )


class TestAIFeedbackTenantEnforcement:
    """Per ADR-0345 Option A: fail-closed per-call tenant check."""

    @pytest.mark.asyncio
    async def test_repo_get_blocks_cross_tenant(self) -> None:
        """InMemoryFeedbackRepository.get() blocks cross-tenant access.

        Per v4 §10 P1 + ADR-0345: cross-tenant access prevented через
        fail-closed filter на ``metadata["tenant_id"]``.
        """
        repo = InMemoryFeedbackRepository()
        await repo.save(_make_doc(doc_id="d-1", tenant="t-a"))

        # Same-tenant access works.
        got = await repo.get("d-1", tenant_id="t-a")
        assert got is not None
        assert got.id == "d-1"

        # Cross-tenant access blocked.
        got_cross = await repo.get("d-1", tenant_id="t-b")
        assert got_cross is None, (
            "Cross-tenant access must be blocked (fail-closed)."
        )

    @pytest.mark.asyncio
    async def test_repo_get_legacy_passes_through(self) -> None:
        """Legacy ``get(doc_id)`` without tenant_id — backwards-compat.

        Per v4 §10 P1: existing callers without tenant_id continue working.
        """
        repo = InMemoryFeedbackRepository()
        await repo.save(_make_doc(doc_id="d-1", tenant="t-a"))

        # Without tenant_id: passes through (legacy compat).
        got_legacy = await repo.get("d-1")
        assert got_legacy is not None, (
            "Legacy get() without tenant_id must continue working "
            "(backwards-compat per v4 §10 P1)."
        )

    @pytest.mark.asyncio
    async def test_repo_get_handles_missing_tenant_in_metadata(self) -> None:
        """Doc without tenant_id в metadata — passes through legacy path.

        Real-world case: doc created without tenant_id (legacy data).
        New code path should NOT silently block (fail-open).
        """
        repo = InMemoryFeedbackRepository()
        await repo.save(_make_doc(doc_id="d-1", tenant=None))

        # Without tenant_id in metadata AND no tenant filter param → pass.
        got = await repo.get("d-1")
        assert got is not None

        # With explicit tenant_id → fail-closed (no tenant_id in doc → mismatch).
        got_filtered = await repo.get("d-1", tenant_id="t-a")
        assert got_filtered is None

    @pytest.mark.asyncio
    async def test_service_get_resolves_tenant_from_context(self) -> None:
        """AIFeedbackService.get() resolves tenant_id from TenantContext.

        Per ADR-0345 Option A: per-call enforcement через TenantContext.
        """
        repo = InMemoryFeedbackRepository()
        await repo.save(_make_doc(doc_id="d-1", tenant="t-a"))
        svc = AIFeedbackService(repository=repo)

        # Set caller tenant context to t-a → access allowed.
        set_tenant(TenantContext(tenant_id="t-a", plan="pro", region="ru"))
        got = await svc.get("d-1")
        assert got is not None

        # Switch to t-b → access blocked.
        set_tenant(TenantContext(tenant_id="t-b", plan="pro", region="ru"))
        got_cross = await svc.get("d-1")
        assert got_cross is None

    @pytest.mark.asyncio
    async def test_service_get_explicit_param_overrides_context(self) -> None:
        """Explicit ``tenant_id=`` param takes priority over TenantContext.

        Per ADR-0345: explicit caller intent is more authoritative.
        """
        repo = InMemoryFeedbackRepository()
        await repo.save(_make_doc(doc_id="d-1", tenant="t-a"))
        svc = AIFeedbackService(repository=repo)

        # Caller context = t-a, but explicit param = t-b → uses t-b.
        set_tenant(TenantContext(tenant_id="t-a", plan="pro", region="ru"))
        got = await svc.get("d-1", tenant_id="t-b")
        assert got is None, (
            "Explicit tenant_id param should take priority over TenantContext."
        )

    @pytest.mark.asyncio
    async def test_service_get_no_tenant_legacy_compat(self) -> None:
        """No TenantContext AND no param — legacy behavior pass-through.

        Per v4 §10 P1 backwards-compat: existing callers without
        tenant setup continue working.
        """
        # Reset any prior context.
        try:
            from src.backend.core.tenancy import _current
            _current.set(None)
        except Exception:
            pass

        repo = InMemoryFeedbackRepository()
        await repo.save(_make_doc(doc_id="d-1", tenant="t-a"))
        svc = AIFeedbackService(repository=repo)

        # No context, no param → legacy pass-through.
        got = await svc.get("d-1")
        assert got is not None
