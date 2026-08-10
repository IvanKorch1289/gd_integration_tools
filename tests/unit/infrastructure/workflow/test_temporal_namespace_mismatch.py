"""D-A8-08 fix (cycle 1): multi-tenant namespace mismatch fail-CLOSED.

Ранее TemporalWorkflowBackend.start_workflow при mismatch namespace
только logger.warning + use client's namespace — silent tenant
isolation bypass (banking context critical, cross-tenant data leak).

Фикс: raise TemporalNamespaceMismatchError при mismatch. Caller должен
создать отдельный Temporal client per namespace (R3 multi-tenant
ADR-045 §opens).
"""


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.workflow.temporal_backend import (
    TemporalNamespaceMismatchError,
    TemporalWorkflowBackend,
)


def _make_client(namespace: str = "tenant-a") -> MagicMock:
    """Mock Temporal client with specific namespace."""
    client = MagicMock()
    client.namespace = namespace
    client.start_workflow = AsyncMock(
        return_value=MagicMock(result_run_id="run-123", first_execution_run_id="run-456"),
    )
    return client


class TestTemporalNamespaceMismatchFailClosed:
    """D-A8-08 fix (cycle 1): namespace mismatch fail-CLOSED."""

    @pytest.mark.asyncio
    async def test_matching_namespace_succeeds(self) -> None:
        """Matching namespace → succeed (regression test)."""
        client = _make_client(namespace="tenant-a")
        backend = TemporalWorkflowBackend(client=client)

        # Не должно raise — namespace matches.
        result = await backend.start_workflow(
            workflow_name="TestWorkflow",
            input={},
            workflow_id="wf-1",
            namespace="tenant-a",
            task_queue="default",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_mismatch_namespace_raises(self) -> None:
        """Mismatch namespace → raise TemporalNamespaceMismatchError (D-A8-08 fix)."""
        client = _make_client(namespace="tenant-a")
        backend = TemporalWorkflowBackend(client=client)

        with pytest.raises(TemporalNamespaceMismatchError) as exc_info:
            await backend.start_workflow(
                workflow_name="TestWorkflow",
                input={},
                workflow_id="wf-1",
                namespace="tenant-b",  # ← mismatch!
                task_queue="default",
            )

        assert "tenant-a" in str(exc_info.value)
        assert "tenant-b" in str(exc_info.value)
        assert "refusing to route" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_global_namespace_normalized_to_default(self) -> None:
        """namespace='global' → 'default' (backward-compat, не raise если client=default)."""
        client = _make_client(namespace="default")
        backend = TemporalWorkflowBackend(client=client)

        # 'global' → 'default' normalization, должен succeed.
        result = await backend.start_workflow(
            workflow_name="TestWorkflow",
            input={},
            workflow_id="wf-global",
            namespace="global",
            task_queue="default",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_global_mismatch_with_non_default_raises(self) -> None:
        """namespace='global' (→ 'default') но client namespace != 'default' → raise."""
        client = _make_client(namespace="tenant-a")
        backend = TemporalWorkflowBackend(client=client)

        with pytest.raises(TemporalNamespaceMismatchError):
            await backend.start_workflow(
                workflow_name="TestWorkflow",
                input={},
                workflow_id="wf-1",
                namespace="global",
                task_queue="default",
            )
