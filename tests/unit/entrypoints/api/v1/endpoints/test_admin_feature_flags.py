"""Unit tests for admin feature-flags endpoints."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.entrypoints.api.v1.endpoints import admin_feature_flags as ff_mod


@pytest.mark.asyncio
async def test_backend_status_returns_in_memory_defaults() -> None:
    """``GET /admin/feature-flags/backend-status"" возвращает статус in-memory backend'а."""
    result = await ff_mod.backend_status()
    assert result["backend"] == "in-memory"
    assert result["ready"] is True
    assert result["flag_count"] > 0
