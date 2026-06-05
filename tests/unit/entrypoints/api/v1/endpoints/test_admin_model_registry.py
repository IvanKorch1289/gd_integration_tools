"""Unit tests for admin_model_registry endpoints (Sprint 11 K4 W6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints import admin_model_registry as mod


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1")
    return app


# ─── _guard_enabled ──────────────────────────────────────────────────────────


def test_guard_enabled_raises_404_when_flag_off() -> None:
    """_guard_enabled raises 404 when ai_model_registry_ui is False."""
    with patch.object(mod.feature_flags, "ai_model_registry_ui", False):
        with pytest.raises(HTTPException) as exc_info:
            mod._guard_enabled()
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "disabled" in exc_info.value.detail


def test_guard_enabled_passes_when_flag_on() -> None:
    """_guard_enabled does nothing when ai_model_registry_ui is True."""
    with patch.object(mod.feature_flags, "ai_model_registry_ui", True):
        mod._guard_enabled()  # no exception


# ─── _composite ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_composite_returns_registry_when_backends_available() -> None:
    """_composite returns CompositeModelRegistry when at least one backend works."""
    mock_registry = MagicMock()
    mock_registry.backend_ids.return_value = ["mlflow"]

    with (
        patch(
            "src.backend.services.ai.model_registry.composite.CompositeModelRegistry",
            return_value=mock_registry,
        ),
        patch(
            "src.backend.services.ai.model_registry.mlflow_backend.MlflowModelRegistry",
            side_effect=ImportError,
        ),
        patch(
            "src.backend.services.ai.model_registry.hf_hub_backend.HuggingFaceModelRegistry",
            return_value=MagicMock(),
        ),
    ):
        result = await mod._composite()

    assert result is mock_registry


@pytest.mark.asyncio
async def test_composite_raises_503_when_no_backends() -> None:
    """_composite raises 503 when no backends are available."""
    with (
        patch(
            "src.backend.services.ai.model_registry.mlflow_backend.MlflowModelRegistry",
            side_effect=ImportError,
        ),
        patch(
            "src.backend.services.ai.model_registry.hf_hub_backend.HuggingFaceModelRegistry",
            side_effect=ImportError,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await mod._composite()

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "no backends" in exc_info.value.detail


# ─── list_models ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_models_returns_data() -> None:
    """list_models returns serialized models and backends."""
    mock_model = MagicMock()
    mock_model.model_dump.return_value = {"name": "gpt-4", "version": "1.0"}

    mock_registry = AsyncMock()
    mock_registry.list_models.return_value = [mock_model]
    mock_registry.backend_ids = MagicMock(return_value=["hf"])

    with (
        patch.object(mod.feature_flags, "ai_model_registry_ui", True),
        patch.object(mod, "_composite", return_value=mock_registry),
    ):
        result = await mod.list_models()

    assert result["count"] == 1
    assert result["backends"] == ["hf"]
    assert result["models"] == [{"name": "gpt-4", "version": "1.0"}]


# ─── get_model ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_model_returns_model_dump() -> None:
    """get_model returns model_dump for existing model."""
    mock_model = MagicMock()
    mock_model.model_dump.return_value = {"name": "gpt-4", "version": "1.0"}

    mock_registry = AsyncMock()
    mock_registry.get_model.return_value = mock_model

    with (
        patch.object(mod.feature_flags, "ai_model_registry_ui", True),
        patch.object(mod, "_composite", return_value=mock_registry),
    ):
        result = await mod.get_model("gpt-4")

    assert result == {"name": "gpt-4", "version": "1.0"}


@pytest.mark.asyncio
async def test_get_model_raises_404_when_missing() -> None:
    """get_model raises 404 when model not found."""
    mock_registry = AsyncMock()
    mock_registry.get_model.return_value = None

    with (
        patch.object(mod.feature_flags, "ai_model_registry_ui", True),
        patch.object(mod, "_composite", return_value=mock_registry),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await mod.get_model("missing")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ─── use_in_route ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_use_in_route_returns_snippet() -> None:
    """use_in_route returns DSL snippet for existing model."""
    mock_model = MagicMock()
    mock_model.name = "gpt-4"
    mock_model.version = "1.0"
    mock_model.extra = {"backend": "openai"}

    mock_registry = AsyncMock()
    mock_registry.get_model.return_value = mock_model

    with (
        patch.object(mod.feature_flags, "ai_model_registry_ui", True),
        patch.object(mod, "_composite", return_value=mock_registry),
    ):
        result = await mod.use_in_route("gpt-4")

    assert result["name"] == "gpt-4"
    assert result["version"] == "1.0"
    assert result["provider"] == "openai"
    assert '.llm_call(provider="openai"' in result["snippet"]


@pytest.mark.asyncio
async def test_use_in_route_defaults_to_huggingface() -> None:
    """use_in_route defaults provider to huggingface when backend missing."""
    mock_model = MagicMock()
    mock_model.name = "bert"
    mock_model.version = "2.0"
    mock_model.extra = {}

    mock_registry = AsyncMock()
    mock_registry.get_model.return_value = mock_model

    with (
        patch.object(mod.feature_flags, "ai_model_registry_ui", True),
        patch.object(mod, "_composite", return_value=mock_registry),
    ):
        result = await mod.use_in_route("bert")

    assert result["provider"] == "huggingface"


@pytest.mark.asyncio
async def test_use_in_route_raises_404_when_missing() -> None:
    """use_in_route raises 404 when model not found."""
    mock_registry = AsyncMock()
    mock_registry.get_model.return_value = None

    with (
        patch.object(mod.feature_flags, "ai_model_registry_ui", True),
        patch.object(mod, "_composite", return_value=mock_registry),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await mod.use_in_route("missing")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ─── HTTP integration ────────────────────────────────────────────────────────


def test_list_models_http_404_when_flag_off() -> None:
    """HTTP GET returns 404 when feature flag is off."""
    app = _make_app()
    with patch.object(mod.feature_flags, "ai_model_registry_ui", False):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/model-registry/models")
    assert resp.status_code == 404


def test_list_models_http_200_when_flag_on() -> None:
    """HTTP GET returns 200 with mocked registry."""
    app = _make_app()
    mock_model = MagicMock()
    mock_model.model_dump.return_value = {"name": "m"}

    mock_registry = AsyncMock()
    mock_registry.list_models.return_value = [mock_model]
    mock_registry.backend_ids = MagicMock(return_value=["hf"])

    with (
        patch.object(mod.feature_flags, "ai_model_registry_ui", True),
        patch.object(mod, "_composite", return_value=mock_registry),
    ):
        client = TestClient(app)
        resp = client.get("/api/v1/admin/model-registry/models")

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
