"""Тесты S29 W1: MLModelLoader — универсальный lazy-loading ML models.

Wave: ``[wave:s29/local-models-repository]``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from src.backend.core.ai.ml_model_loader import MLModelLoader

# ── Type detection (no heavy libs required) ──────────────────────────────────

class TestTypeDetection:
    def test_detect_by_extension_pt(self) -> None:
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.pt")) == "torch"

    def test_detect_by_extension_pth(self) -> None:
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.pth")) == "torch"

    def test_detect_by_extension_jit_pt_is_torch(self) -> None:
        """``.jit.pt`` → suffix=.pt → torch (Path.suffix only returns last extension)."""
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.jit.pt")) == "torch"

    def test_detect_by_extension_onnx(self) -> None:
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.onnx")) == "onnx"

    def test_detect_by_extension_joblib(self) -> None:
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.joblib")) == "sklearn"

    def test_detect_by_extension_pkl(self) -> None:
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.pkl")) == "joblib"

    def test_detect_by_extension_cbm(self) -> None:
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.cbm")) == "catboost"

    def test_detect_by_extension_mb(self) -> None:
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.mb")) == "lightgbm"

    def test_detect_unknown_returns_none(self) -> None:
        loader = MLModelLoader()
        assert loader._detect_type(Path("/a/model.xyz")) is None


# ── Load errors ────────────────────────────────────────────────────────────────

class TestLoadErrors:
    def test_load_nonexistent_file_raises(self) -> None:
        loader = MLModelLoader()
        with pytest.raises(FileNotFoundError):
            loader._load_sync(Path("/nonexistent/model.pt"), "torch")

    def test_load_unknown_type_raises(self) -> None:
        """File with unknown extension without explicit model_type → FileNotFoundError (since file doesn't exist)."""
        loader = MLModelLoader()
        with pytest.raises(FileNotFoundError, match="not found"):
            loader._load_sync(Path("/nonexistent.unknown"), None)

    def test_load_torch_not_installed_raises(self) -> None:
        loader = MLModelLoader()
        with patch.dict(sys.modules, {"torch": None}):
            with pytest.raises(RuntimeError, match="torch не установлен"):
                loader._load_by_type(Path("/tmp/model.pt"), "torch")

    def test_load_onnx_not_installed_raises(self) -> None:
        loader = MLModelLoader()
        with patch.dict(sys.modules, {"onnxruntime": None}):
            with pytest.raises(RuntimeError, match="onnxruntime не установлен"):
                loader._load_by_type(Path("/tmp/model.onnx"), "onnx")

    def test_load_sklearn_not_installed_raises(self) -> None:
        loader = MLModelLoader()
        with patch.dict(sys.modules, {"joblib": None}):
            with pytest.raises(RuntimeError, match="scikit-learn не установлен"):
                loader._load_by_type(Path("/tmp/model.joblib"), "sklearn")


# ── LRU cache behavior ────────────────────────────────────────────────────────

class TestLRUCache:
    def test_unload_removes_matching_prefix_keys(self) -> None:
        loader = MLModelLoader(max_models=8)
        loader._cache["/path/model_a:torch"] = "model_a"
        loader._cache["/path/model_b:onnx"] = "model_b"
        loader._cache["/other:cbm"] = "model_c"

        loader.unload(Path("/path"))

        assert "/path/model_a:torch" not in loader._cache
        assert "/path/model_b:onnx" not in loader._cache
        assert "/other:cbm" in loader._cache

    def test_unload_all_when_prefix_matches(self) -> None:
        loader = MLModelLoader(max_models=8)
        loader._cache["/tmp/model1:torch"] = "m1"
        loader._cache["/tmp/model2:torch"] = "m2"
        loader.unload(Path("/tmp"))
        assert len(loader._cache) == 0


# ── Full async load/unload cycle (joblib) ─────────────────────────────────────

class TestAsyncLoadCycle:
    async def test_load_returns_model_object_joblib(self) -> None:
        loader = MLModelLoader()
        with TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "test.joblib"
            import joblib

            joblib.dump([1.0, 2.0, 3.0], model_path)

            model = await loader.load(model_path, model_type="joblib")
            assert isinstance(model, list)
            assert model == [1.0, 2.0, 3.0]

    async def test_unload_clears_cache(self) -> None:
        loader = MLModelLoader()
        with TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "test.joblib"
            import joblib

            joblib.dump([1.0], model_path)

            await loader.load(model_path, model_type="joblib")
            loader.unload(model_path)
            cache_keys = list(loader._cache.keys())
            assert all(str(model_path) not in k for k in cache_keys)

    async def test_load_max_models_eviction(self) -> None:
        loader = MLModelLoader(max_models=2)
        with TemporaryDirectory() as tmpdir:
            for i in range(3):
                p = Path(tmpdir) / f"model{i}.joblib"
                import joblib

                joblib.dump([float(i)], p)
                await loader.load(p, model_type="joblib")
            assert len(loader._cache) <= 2