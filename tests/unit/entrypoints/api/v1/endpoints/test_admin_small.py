"""Unit tests for small admin endpoints."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.api.v1.endpoints import (
    admin_feedback as feedback_mod,
    admin_rag as rag_mod,
    asyncapi as asyncapi_mod,
)


# ─── admin_feedback ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_training_runs() -> None:
    result = await feedback_mod.list_training_runs(limit=5)
    assert result == {"runs": [], "count": 0, "limit": 5}


@pytest.mark.asyncio
async def test_labeled_count_with_service() -> None:
    with patch(
        "src.backend.services.ai.feedback.feedback_service.AIFeedbackService"
    ) as mock_cls:
        svc = AsyncMock()
        svc.list_labeled.return_value = [{"id": 1}, {"id": 2}]
        mock_cls.return_value = svc
        result = await feedback_mod.labeled_count(tenant_id="t1")
        assert result["tenant_id"] == "t1"
        assert result["count"] == 2


@pytest.mark.asyncio
async def test_labeled_count_service_error() -> None:
    with patch(
        "src.backend.services.ai.feedback.feedback_service.AIFeedbackService",
        side_effect=ImportError,
    ):
        result = await feedback_mod.labeled_count(tenant_id="t1")
        assert result["count"] == 0


# ─── admin_rag ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_strategy_stats() -> None:
    with patch(
        "src.backend.services.ai.rag.strategy_selector.AdaptiveStrategySelector"
    ) as mock_cls:
        selector = MagicMock()
        selector.stats.return_value = {"dense": 5, "sparse": 3}
        mock_cls.return_value = selector
        with patch(
            "src.backend.core.config.features.feature_flags.adaptive_rag_strategy", True
        ):
            result = await rag_mod.strategy_stats()
            assert result["strategies"] == {"dense": 5, "sparse": 3}
            assert result["total"] == 8
            assert result["feature_enabled"] is True


# ─── asyncapi ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_asyncapi_yaml() -> None:
    with patch.object(
        asyncapi_mod, "build_asyncapi_yaml", return_value="asyncapi: 3.0"
    ):
        result = await asyncapi_mod.get_asyncapi_yaml()
        assert result.media_type == "application/yaml"
        assert result.body == b"asyncapi: 3.0"


@pytest.mark.asyncio
async def test_get_asyncapi_json() -> None:
    with patch.object(
        asyncapi_mod, "build_asyncapi_json", return_value='{"asyncapi": "3.0"}'
    ):
        result = await asyncapi_mod.get_asyncapi_json()
        assert result.media_type == "application/json"
        assert result.body == b'{"asyncapi": "3.0"}'
