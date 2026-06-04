"""Тесты AI Model Registry (Wave [wave:s8/k4-model-registry]).

ModelRecord (Pydantic): валидация полей.
MlflowModelRegistry: с MagicMock'нутым MlflowClient (без реального mlflow).
HuggingFaceModelRegistry: с MagicMock'нутым HfApi (без реального huggingface_hub).
"""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.services.ai.model_registry import (
    HuggingFaceModelRegistry,
    MlflowModelRegistry,
    ModelRecord,
)

pytestmark = pytest.mark.asyncio


# ── ModelRecord ──────────────────────────────────────────────────────────


def test_model_record_defaults() -> None:
    rec = ModelRecord(name="m")
    assert rec.version == "1"
    assert rec.stage == "None"
    assert rec.tags == {}


def test_model_record_rejects_invalid_stage() -> None:
    with pytest.raises(Exception):
        ModelRecord(name="m", stage="ProductionPlus")  # type: ignore[arg-type]


# ── MlflowModelRegistry ──────────────────────────────────────────────────


def _make_mlflow_model_version(
    name: str, version: str, stage: str = "Production"
) -> MagicMock:
    """MagicMock с атрибутами, имитирующий mlflow.ModelVersion."""
    mv = MagicMock()
    mv.name = name
    mv.version = version
    mv.current_stage = stage
    mv.source = f"s3://bucket/{name}/{version}"
    mv.description = "test model"
    mv.tags = []
    return mv


def _install_fake_mlflow(
    monkeypatch: pytest.MonkeyPatch, client_mock: MagicMock
) -> None:
    """Подменяет ``mlflow.tracking`` модулем-заглушкой с нашим клиентом."""
    fake_mlflow = types.ModuleType("mlflow")
    fake_tracking = types.ModuleType("mlflow.tracking")
    fake_tracking.MlflowClient = lambda **kwargs: client_mock  # type: ignore[attr-defined]
    fake_mlflow.tracking = fake_tracking  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)
    monkeypatch.setitem(sys.modules, "mlflow.tracking", fake_tracking)


async def test_mlflow_get_model_by_version(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_model_version.return_value = _make_mlflow_model_version(
        "rs", "3", "Staging"
    )
    _install_fake_mlflow(monkeypatch, client)

    reg = MlflowModelRegistry("http://mlflow:5000")
    rec = await reg.get_model("rs", version="3")

    assert rec is not None
    assert rec.name == "rs"
    assert rec.version == "3"
    assert rec.stage == "Staging"


async def test_mlflow_get_model_latest_production_when_no_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.get_latest_versions.return_value = [
        _make_mlflow_model_version("rs", "5", "Production")
    ]
    _install_fake_mlflow(monkeypatch, client)

    reg = MlflowModelRegistry("http://mlflow:5000")
    rec = await reg.get_model("rs")

    assert rec is not None
    assert rec.version == "5"
    client.get_latest_versions.assert_called_once_with("rs", stages=["Production"])


async def test_mlflow_list_models_flattens_latest_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rm = MagicMock()
    rm.latest_versions = [
        _make_mlflow_model_version("a", "1"),
        _make_mlflow_model_version("a", "2", "Production"),
    ]
    client = MagicMock()
    client.search_registered_models.return_value = [rm]
    _install_fake_mlflow(monkeypatch, client)

    reg = MlflowModelRegistry("http://mlflow:5000")
    items = await reg.list_models()

    assert len(items) == 2
    assert {r.version for r in items} == {"1", "2"}


async def test_mlflow_transition_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    moved = _make_mlflow_model_version("rs", "3", "Production")
    client = MagicMock()
    client.transition_model_version_stage.return_value = moved
    _install_fake_mlflow(monkeypatch, client)

    reg = MlflowModelRegistry("http://mlflow:5000")
    rec = await reg.transition_stage("rs", "3", "Production")

    assert rec.stage == "Production"


async def test_mlflow_missing_module_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force ImportError из ``mlflow.tracking``.
    monkeypatch.setitem(sys.modules, "mlflow", None)
    monkeypatch.setitem(sys.modules, "mlflow.tracking", None)

    reg = MlflowModelRegistry("http://mlflow:5000")
    with pytest.raises(RuntimeError, match="mlflow не установлен"):
        await reg.list_models()


# ── HuggingFaceModelRegistry ─────────────────────────────────────────────


def _install_fake_hf(monkeypatch: pytest.MonkeyPatch, api_mock: MagicMock) -> None:
    fake_hf = types.ModuleType("huggingface_hub")
    fake_hf.HfApi = lambda **kw: api_mock  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)


async def test_hf_get_model_returns_record(monkeypatch: pytest.MonkeyPatch) -> None:
    info = MagicMock()
    info.modelId = "openai/gpt-2"
    info.sha = "abc123"
    info.tags = ["stage:Production", "framework:pytorch"]
    info.description = "GPT-2"

    api = MagicMock()
    api.model_info.return_value = info
    _install_fake_hf(monkeypatch, api)

    reg = HuggingFaceModelRegistry(token="hf_test")
    rec = await reg.get_model("openai/gpt-2")

    assert rec is not None
    assert rec.name == "openai/gpt-2"
    assert rec.stage == "Production"
    assert rec.tags == {"framework": "pytorch"}
    assert rec.artifact_uri.startswith("hf://")  # type: ignore[union-attr]


async def test_hf_get_model_not_found_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = MagicMock()
    api.model_info.side_effect = RuntimeError("404")
    _install_fake_hf(monkeypatch, api)

    reg = HuggingFaceModelRegistry()
    rec = await reg.get_model("nonexistent")

    assert rec is None


async def test_hf_transition_stage_emulates_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = MagicMock()
    info.modelId = "x/y"
    info.sha = "abc"
    info.tags = []
    info.description = "x"

    api = MagicMock()
    api.model_info.return_value = info
    _install_fake_hf(monkeypatch, api)

    reg = HuggingFaceModelRegistry()
    rec = await reg.transition_stage("x/y", "main", "Production")

    assert rec.stage == "Production"


async def test_hf_missing_module_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    reg = HuggingFaceModelRegistry()
    with pytest.raises(RuntimeError, match="huggingface_hub не установлен"):
        await reg.list_models()
