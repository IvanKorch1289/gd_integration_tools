"""Regression tests для cross-tenant enforcement в MongoNotebookRepository (Option A, ADR-0345).

Per v4 §10 P1 '0 importers + migration window + contract test':
contract tests verify fail-closed behavior в MongoNotebookRepository.

Cycle 158+ implementation: добавлен ``tenant_id`` parameter в
``MongoNotebookRepository.get()``. Per v4 §3 evidence-first, эти tests
verify behavior с mock Mongo client (no real Mongo infrastructure).

NOTE: This file uses AsyncMock для MongoDBClient — production code
requires real Mongo testing per integration suite (out of cycle 158+
scope).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_pydantic_settings(monkeypatch):
    """Stub ``get_mongo_client`` so we can construct MongoNotebookRepository."""
    fake_client = MagicMock()
    fake_client_factory = MagicMock(return_value=fake_client)
    monkeypatch.setattr(
        "src.backend.infrastructure.repositories.notebooks_mongo.get_mongo_client",
        fake_client_factory,
    )
    return fake_client


class TestMongoNotebookRepositoryTenantEnforcement:
    """Per ADR-0345 Option A: fail-closed per-call tenant check."""

    @pytest.mark.asyncio
    async def test_get_blocks_cross_tenant(self, mock_pydantic_settings) -> None:
        """Cross-tenant access prevented at Mongo repo level."""
        from src.backend.infrastructure.repositories.notebooks_mongo import (
            MongoNotebookRepository,
        )

        repo = MongoNotebookRepository()
        # Mock find_one to return doc with tenant_id=t-a.
        mock_pydantic_settings.find_one = AsyncMock(
            return_value={
                "_id": "nb-1",
                "title": "Test",
                "tags": [],
                "latest_version": 0,
                "created_by": "user@bank.local",
                "metadata": {"tenant_id": "t-a"},
            }
        )

        # Same-tenant access works.
        got = await repo.get("nb-1", tenant_id="t-a")
        assert got is not None
        assert got.id == "nb-1"

        # Cross-tenant access blocked (fail-closed).
        got_cross = await repo.get("nb-1", tenant_id="t-b")
        assert got_cross is None, (
            "Cross-tenant Mongo access must be blocked (fail-closed)."
        )

    @pytest.mark.asyncio
    async def test_get_legacy_fails_closed_without_tenant(
        self, mock_pydantic_settings
    ) -> None:
        """v6 W3 (25.09 audit): ``get(notebook_id)`` без tenant_id → None.

        Per ADR-0345 fail-closed: user-data API запрещает None/пустой tenant.
        Legacy-compat обратная дверь закрыта.
        """
        from src.backend.infrastructure.repositories.notebooks_mongo import (
            MongoNotebookRepository,
        )

        repo = MongoNotebookRepository()
        mock_pydantic_settings.find_one = AsyncMock(
            return_value={
                "_id": "nb-1",
                "title": "Test",
                "tags": [],
                "latest_version": 0,
                "created_by": "user@bank.local",
                "metadata": {"tenant_id": "t-a"},
            }
        )

        # Without tenant_id: FAIL-CLOSED → None (не возвращаем данные).
        got_no_tenant = await repo.get("nb-1", tenant_id="")
        assert got_no_tenant is None, (
            "FAIL_CLOSED_VIOLATION: get() with empty tenant_id returned "
            "data instead of None. Per ADR-0345: user-data API must reject "
            "empty tenant."
        )

    @pytest.mark.asyncio
    async def test_get_handles_missing_tenant_in_doc(
        self, mock_pydantic_settings
    ) -> None:
        """Doc без tenant_id в metadata + explicit filter → None (fail-closed)."""
        from src.backend.infrastructure.repositories.notebooks_mongo import (
            MongoNotebookRepository,
        )

        repo = MongoNotebookRepository()
        mock_pydantic_settings.find_one = AsyncMock(
            return_value={
                "_id": "nb-1",
                "title": "Test",
                "tags": [],
                "latest_version": 0,
                "created_by": "user@bank.local",
                "metadata": {},  # No tenant_id.
            }
        )

        # With explicit tenant_id → fail-closed (no tenant_id in doc → mismatch).
        got_filtered = await repo.get("nb-1", tenant_id="t-a")
        assert got_filtered is None

        # Empty tenant_id → also fail-closed (per ADR-0345).
        got_empty = await repo.get("nb-1", tenant_id="")
        assert got_empty is None
