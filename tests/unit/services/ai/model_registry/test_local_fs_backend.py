"""Тесты S29 W2: LocalFSModelRegistry — filesystem-based model registry.

Wave: ``[wave:s29/local-models-repository]``.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.backend.services.ai.model_registry.local_fs_backend import LocalFSModelRegistry

pytestmark = pytest.mark.asyncio


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _write_manifest(root: Path, name: str, version: str = "v1", **kwargs) -> Path:
    """Создаёт каталог модели с manifest.json по пути ``root/models/<name>/``."""
    models_root = root / "models"
    model_dir = models_root / name.replace("/", "_")
    model_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": version,
        "framework": "torch",
        "description": f"Test model {name}",
        "tags": {"team": "ml", "env": "test"},
        "stage": "Production",
        "created_at": "2026-01-01T00:00:00Z",
        **kwargs,
    }
    (model_dir / ".model_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return model_dir


# ── Model discovery ───────────────────────────────────────────────────────────


async def test_list_models_returns_empty_when_no_models() -> None:
    with TemporaryDirectory() as tmpdir:
        registry = LocalFSModelRegistry(workspace_path=tmpdir)
        result = await registry.list_models()
        assert result == []


async def test_list_models_finds_one_model() -> None:
    with TemporaryDirectory() as tmpdir:
        _write_manifest(Path(tmpdir), "credit_model", "v1")
        registry = LocalFSModelRegistry(workspace_path=tmpdir)

        records = await registry.list_models()
        assert len(records) == 1
        assert records[0].name == "credit_model"
        assert records[0].version == "v1"


async def test_list_models_ignores_dirs_without_manifest() -> None:
    with TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "models" / "no_manifest").mkdir(parents=True)
        _write_manifest(Path(tmpdir), "has_manifest", "v1")
        registry = LocalFSModelRegistry(workspace_path=tmpdir)

        records = await registry.list_models()
        assert len(records) == 1
        assert records[0].name == "has_manifest"


async def test_list_models_skips_malformed_manifest() -> None:
    with TemporaryDirectory() as tmpdir:
        bad_dir = Path(tmpdir) / "models" / "bad_manifest"
        bad_dir.mkdir(parents=True)
        (bad_dir / ".model_manifest.json").write_text(
            "{invalid json}", encoding="utf-8"
        )
        _write_manifest(Path(tmpdir), "good_model", "v1")
        registry = LocalFSModelRegistry(workspace_path=tmpdir)

        records = await registry.list_models()
        assert len(records) == 1
        assert records[0].name == "good_model"


# ── get_model ─────────────────────────────────────────────────────────────────


async def test_get_model_finds_by_name() -> None:
    with TemporaryDirectory() as tmpdir:
        _write_manifest(Path(tmpdir), "score_model", "v2")
        registry = LocalFSModelRegistry(workspace_path=tmpdir)

        rec = await registry.get_model("score_model")
        assert rec is not None
        assert rec.name == "score_model"
        assert rec.version == "v2"


async def test_get_model_filters_by_version() -> None:
    """Version filter: directory name is unique, version stored in manifest."""
    with TemporaryDirectory() as tmpdir:
        _write_manifest(Path(tmpdir), "ver_model", "v1")
        registry = LocalFSModelRegistry(workspace_path=tmpdir)

        rec = await registry.get_model("ver_model", version="v1")
        assert rec is not None
        assert rec.version == "v1"


async def test_get_model_filters_by_stage() -> None:
    with TemporaryDirectory() as tmpdir:
        _write_manifest(Path(tmpdir), "stage_model", "v1", stage="Staging")
        registry = LocalFSModelRegistry(workspace_path=tmpdir)

        rec = await registry.get_model("stage_model", stage="Staging")
        assert rec is not None
        assert rec.stage == "Staging"


async def test_get_model_returns_none_when_not_found() -> None:
    with TemporaryDirectory() as tmpdir:
        registry = LocalFSModelRegistry(workspace_path=tmpdir)
        rec = await registry.get_model("nonexistent")
        assert rec is None


# ── register_model ─────────────────────────────────────────────────────────────


async def test_register_model_creates_dir_and_manifest() -> None:
    with TemporaryDirectory() as tmpdir:
        registry = LocalFSModelRegistry(workspace_path=tmpdir)

        from src.backend.services.ai.model_registry.adapter import ModelRecord

        record = ModelRecord(
            name="new_model",
            version="v1",
            stage="Production",
            tags={"framework": "sklearn"},
            description="New test model",
        )
        result = await registry.register_model(record)

        assert result.name == "new_model"
        assert result.artifact_uri is not None

        manifest_path = Path(tmpdir) / "models" / "new_model" / ".model_manifest.json"
        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded["name"] == "new_model"
        assert loaded["framework"] == "sklearn"


# ── transition_stage ───────────────────────────────────────────────────────────


async def test_transition_stage_updates_manifest() -> None:
    with TemporaryDirectory() as tmpdir:
        _write_manifest(Path(tmpdir), "trans_model", "v1", stage="Production")
        registry = LocalFSModelRegistry(workspace_path=tmpdir)

        result = await registry.transition_stage("trans_model", "v1", "Archived")
        assert result.stage == "Archived"

        manifest_path = Path(tmpdir) / "models" / "trans_model" / ".model_manifest.json"
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded["stage"] == "Archived"


async def test_transition_stage_raises_when_not_found() -> None:
    with TemporaryDirectory() as tmpdir:
        registry = LocalFSModelRegistry(workspace_path=tmpdir)
        with pytest.raises(FileNotFoundError):
            await registry.transition_stage("nonexistent", "v1", "Archived")
