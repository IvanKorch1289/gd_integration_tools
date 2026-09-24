"""Regression tests: W11 P0 privacy erasure — tenant-aware propagation.

Per ADR-0345 Option A + v4 §10 P0 'privacy erasure backends':
оркестратор + S3/Qdrant/Langmem адаптеры обязаны принимать ``tenant_id``
(per-call override) и резолвить через TenantContext при отсутствии.

Scope (W11 P0):
- Orchestrator: accept + resolve + pass through tenant_id.
- S3: prefix-based filter ``tenants/{tenant_id}/{subject_type}/{subject_id}/``
      (no schema change required). Fail-closed if tenant_id unavailable.
- Qdrant: filter expression includes tenant_id when provided (requires
      ``tenant_id`` field in vector payload — schema contract deferred).
- LangMem: signature accepts tenant_id, applies SQL filter when model
      has ``tenant_id`` column (migration deferred — logs warning otherwise).

Honest scope notes (per audit "Не завышай"):
- Postgres/Redis: tenant-aware filtering ALREADY implemented (cycle 158+).
- Qdrant payload schema: NOT yet guaranteed — filter is no-op без schema fix.
- LangMem model: NOT yet имеет tenant_id column — filter is no-op без migration.
- Backwards-compat: legacy callers without tenant_id получают warning +
  аудит-event (fail-open only для Postgres/Redis, fail-closed для S3).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.privacy import (
    DeleteDataSubject,
    ErasureResultStatus,
    ErasureStrategy,
    LangMemErasureAdapter,
    QdrantErasureAdapter,
    S3ErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject._types import ErasureAdapter


class TestProtocolConformance:
    """ErasureAdapter Protocol: ``execute()`` accepts tenant_id keyword-only."""

    @pytest.mark.parametrize(
        "adapter_cls", [S3ErasureAdapter, QdrantErasureAdapter, LangMemErasureAdapter]
    )
    def test_adapter_accepts_tenant_id_param(self, adapter_cls: type) -> None:
        """Все 3 deferred-адаптера принимают ``tenant_id`` keyword-only."""
        import inspect

        # Use ``getattr(adapter_cls, "execute")`` чтобы избежать mypy
        # "type has no attribute execute" (type objects don't have arbitrary
        # attributes by default — нужна metaclass dance, либо runtime check).
        execute_fn = getattr(adapter_cls, "execute", None)
        assert execute_fn is not None, f"{adapter_cls.__name__}.execute missing"
        sig = inspect.signature(execute_fn)
        assert "tenant_id" in sig.parameters, (
            f"{adapter_cls.__name__}.execute missing tenant_id parameter"
        )
        param = sig.parameters["tenant_id"]
        assert param.default is None, (
            f"{adapter_cls.__name__}.execute tenant_id default must be None"
        )
        assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"{adapter_cls.__name__}.execute tenant_id must be keyword-only"
        )

    def test_protocol_signature_has_tenant_id(self) -> None:
        """ErasureAdapter Protocol declares ``tenant_id`` keyword-only param."""
        import inspect

        sig = inspect.signature(ErasureAdapter.execute)
        assert "tenant_id" in sig.parameters


class TestOrchestratorTenantPropagation:
    """DeleteDataSubject: accept + resolve + pass tenant_id to adapters."""

    @pytest.mark.asyncio
    async def test_explicit_tenant_id_passes_through_to_adapter(self) -> None:
        """Explicit tenant_id пробрасывается в adapter.execute()."""
        captured: dict[str, Any] = {}

        class CapturingAdapter:
            """Захватывает kwargs из execute() для проверки propagation."""

            name = "capturing"

            async def execute(
                self,
                subject_id: str,
                subject_type: str,
                strategy: ErasureStrategy,
                correlation_id: str,
                *,
                tenant_id: str | None = None,
            ) -> Any:
                captured.update(
                    {
                        "subject_id": subject_id,
                        "subject_type": subject_type,
                        "strategy": strategy,
                        "correlation_id": correlation_id,
                        "tenant_id": tenant_id,
                    }
                )
                from src.backend.core.privacy import AdapterResult

                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SUCCESS,
                    duration_ms=0.0,
                )

        # Cast to ErasureAdapter для type checker (structural Protocol match).
        adapter: ErasureAdapter = CapturingAdapter()  # type: ignore[assignment]
        orchestrator = DeleteDataSubject(adapters=[adapter])
        result = await orchestrator.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.HARD_DELETE,
            tenant_id="tenant-A",
        )

        assert captured["tenant_id"] == "tenant-A"
        assert result.success

    @pytest.mark.asyncio
    async def test_orchestrator_signature_accepts_tenant_id(self) -> None:
        """DeleteDataSubject.execute() имеет tenant_id keyword-only param."""
        import inspect

        sig = inspect.signature(DeleteDataSubject.execute)
        assert "tenant_id" in sig.parameters
        param = sig.parameters["tenant_id"]
        assert param.kind == inspect.Parameter.KEYWORD_ONLY
        assert param.default is None

    @pytest.mark.asyncio
    async def test_legacy_no_tenant_id_path_does_not_raise(self) -> None:
        """Backwards-compat: caller без tenant_id + no context — НЕ raise.

        Per v4 §4.3 backwards-compat: legacy callers continue working.
        TenantContext resolution failure → warning log + adapter-level
        TenantContext fallback (Postgres/Redis use ``current_tenant()``).
        S3 fails-closed at adapter level (covered in TestS3TenantFailClosed).
        """
        captured: dict[str, Any] = {}

        class CapturingAdapter:
            """Захватывает kwargs из execute() для проверки legacy path."""

            name = "capturing"

            async def execute(
                self,
                subject_id: str,
                subject_type: str,
                strategy: ErasureStrategy,
                correlation_id: str,
                *,
                tenant_id: str | None = None,
            ) -> Any:
                captured["tenant_id"] = tenant_id
                from src.backend.core.privacy import AdapterResult

                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SUCCESS,
                    duration_ms=0.0,
                )

        adapter: ErasureAdapter = CapturingAdapter()  # type: ignore[assignment]
        orchestrator = DeleteDataSubject(adapters=[adapter])
        # No tenant_id, no TenantContext set.
        result = await orchestrator.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.HARD_DELETE,
        )

        # Adapter receives tenant_id=None or empty string (resolved via
        # TenantContext — returns "" когда context пуст, not None/raise).
        # Per audit "Всегда перепроверяй": legacy path MUST NOT raise.
        assert not captured["tenant_id"]
        assert result.success


class TestS3TenantFailClosed:
    """S3 adapter: fails-closed без tenant_id (security-critical)."""

    @pytest.mark.asyncio
    async def test_s3_fails_closed_without_tenant_id(self) -> None:
        """S3 без tenant_id + no context → FAILED (fail-closed)."""
        adapter = S3ErasureAdapter(bucket_name="test-bucket")
        result = await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.HARD_DELETE,
            correlation_id="test-corr",
            # NO tenant_id — no TenantContext set.
        )

        assert result.status == ErasureResultStatus.FAILED
        assert "tenant_id required" in (result.error or "")

    @pytest.mark.asyncio
    async def test_s3_with_explicit_tenant_id_proceeds(self) -> None:
        """S3 with explicit tenant_id → attempt connection (may fail with mock).

        Smoke test: signature accepts tenant_id without TypeError. Actual
        S3 operation fails on missing aioboto3 but that's expected SKIPPED.
        """
        adapter = S3ErasureAdapter(bucket_name="test-bucket")
        # Smoke: just verify the keyword-only param works (no TypeError).
        result = await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.HARD_DELETE,
            correlation_id="test-corr",
            tenant_id="tenant-A",
        )

        # Result will be SKIPPED (aioboto3 not installed in dev env) — that's OK.
        assert result.adapter_name == "s3"
        assert result.status in (
            ErasureResultStatus.SKIPPED,
            ErasureResultStatus.SUCCESS,
            ErasureResultStatus.FAILED,
        )


class TestQdrantTenantAcceptance:
    """Qdrant adapter: accepts tenant_id (filter is forward-compatible)."""

    @pytest.mark.asyncio
    async def test_qdrant_accepts_tenant_id_without_typeerror(self) -> None:
        """Qdrant.execute() принимает tenant_id keyword-only без TypeError."""
        adapter = QdrantErasureAdapter(collection_name="test")
        # Smoke: just verify signature.
        result = await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.HARD_DELETE,
            correlation_id="test-corr",
            tenant_id="tenant-A",
        )

        # Без qdrant-client → SKIPPED (ожидаемо в dev env).
        assert result.adapter_name == "qdrant"
        assert result.status in (
            ErasureResultStatus.SKIPPED,
            ErasureResultStatus.SUCCESS,
            ErasureResultStatus.FAILED,
        )


class TestLangMemTenantAcceptance:
    """LangMem adapter: accepts tenant_id (filter applies if column exists)."""

    @pytest.mark.asyncio
    async def test_langmem_accepts_tenant_id_without_typeerror(self) -> None:
        """LangMem.execute() принимает tenant_id keyword-only без TypeError."""
        adapter = LangMemErasureAdapter()
        # Smoke: just verify signature (SKIPPED без session_factory).
        result = await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.HARD_DELETE,
            correlation_id="test-corr",
            tenant_id="tenant-A",
        )

        assert result.adapter_name == "langmem"
        assert result.status == ErasureResultStatus.SKIPPED  # no session_factory
