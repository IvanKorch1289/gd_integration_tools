"""Тесты Sprint 11 K4 W6 — CompositeModelRegistry."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.model_registry.adapter import ModelRecord
from src.backend.services.ai.model_registry.composite import CompositeModelRegistry


def _make_adapter(models: list[ModelRecord]) -> AsyncMock:
    adapter = AsyncMock()
    adapter.list_models = AsyncMock(return_value=models)
    adapter.get_model = AsyncMock(
        side_effect=lambda name, version=None, stage=None: next(
            (
                m
                for m in models
                if m.name == name and (version is None or m.version == version)
            ),
            None,
        )
    )
    adapter.register_model = AsyncMock(side_effect=lambda r: r)
    adapter.transition_stage = AsyncMock(side_effect=lambda n, v, s: models[0])
    return adapter


def test_construction_requires_backends() -> None:
    """Пустой dict backends → ValueError."""
    with pytest.raises(ValueError):
        CompositeModelRegistry({})


@pytest.mark.asyncio
async def test_list_models_merges_all_backends() -> None:
    """list_models() сводит результаты из MLflow + HF Hub."""
    mlflow_models = [ModelRecord(name="mlflow-1", version="1", stage="Production")]
    hf_models = [ModelRecord(name="hf-1", version="0.1.0", stage="None")]
    registry = CompositeModelRegistry(
        {
            "mlflow": _make_adapter(mlflow_models),
            "huggingface": _make_adapter(hf_models),
        }
    )

    models = await registry.list_models()
    names = {m.name for m in models}
    assert names == {"mlflow-1", "hf-1"}
    backends = {m.extra["backend"] for m in models}
    assert backends == {"mlflow", "huggingface"}


@pytest.mark.asyncio
async def test_get_model_searches_all_backends_when_no_filter() -> None:
    """Без backend-filter поиск идёт по всем."""
    only_hf = [ModelRecord(name="bge-m3", version="2.0")]
    registry = CompositeModelRegistry(
        {"mlflow": _make_adapter([]), "huggingface": _make_adapter(only_hf)}
    )
    found = await registry.get_model("bge-m3")
    assert found is not None
    assert found.extra["backend"] == "huggingface"


@pytest.mark.asyncio
async def test_register_model_writes_to_primary() -> None:
    """register_model по умолчанию пишет в primary (mlflow)."""
    mlflow_adapter = _make_adapter([])
    hf_adapter = _make_adapter([])
    registry = CompositeModelRegistry(
        {"mlflow": mlflow_adapter, "huggingface": hf_adapter}
    )
    new = ModelRecord(name="new-model", version="1", stage="None")
    out = await registry.register_model(new)
    mlflow_adapter.register_model.assert_awaited_once()
    hf_adapter.register_model.assert_not_awaited()
    assert out.extra["backend"] == "mlflow"


@pytest.mark.asyncio
async def test_register_with_explicit_backend() -> None:
    """register_model(backend='huggingface') пишет в hf."""
    mlflow_adapter = _make_adapter([])
    hf_adapter = _make_adapter([])
    registry = CompositeModelRegistry(
        {"mlflow": mlflow_adapter, "huggingface": hf_adapter}
    )
    new = ModelRecord(name="bge-m3", version="1")
    await registry.register_model(new, backend="huggingface")
    hf_adapter.register_model.assert_awaited_once()
    mlflow_adapter.register_model.assert_not_awaited()
