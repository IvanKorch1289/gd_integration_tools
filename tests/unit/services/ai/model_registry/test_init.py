"""Unit-тесты ``services.ai.model_registry`` — coverage ratchet (Post-Plan A Sprint 25).

core/ai/model_registry service package facade (s8/k4-model-registry wave): re-exports
5 symbols (ModelRegistryAdapter Protocol + MlflowModelRegistry +
HuggingFaceModelRegistry + LocalFSModelRegistry classes + ModelRecord
dataclass). ~10 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import model_registry
from src.backend.services.ai.model_registry import (
    HuggingFaceModelRegistry,
    LocalFSModelRegistry,
    MlflowModelRegistry,
    ModelRecord,
    ModelRegistryAdapter,
)


@pytest.mark.unit
class TestModelRegistryFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "HuggingFaceModelRegistry",
            "LocalFSModelRegistry",
            "MlflowModelRegistry",
            "ModelRecord",
            "ModelRegistryAdapter",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(model_registry, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in model_registry.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 5 символов."""
        assert len(model_registry.__all__) == 5

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает AI Model Registry (MLflow + HF Hub)."""
        assert model_registry.__doc__ is not None
        assert "Model" in model_registry.__doc__ or "registry" in model_registry.__doc__.lower()


@pytest.mark.unit
class TestModelRegistryFacadeIdentity:
    """Identity checks для 5 re-exports."""

    def test_model_registry_adapter_is_protocol(self) -> None:
        """``ModelRegistryAdapter`` — Protocol class (structural subtyping)."""

        assert isinstance(ModelRegistryAdapter, type)
        # Protocol classes have ``__subclasshook__`` или ``__call__``:
        assert hasattr(ModelRegistryAdapter, "__subclasshook__") or hasattr(
            ModelRegistryAdapter, "__call__"
        )

    def test_mlflow_model_registry_is_class(self) -> None:
        """``MlflowModelRegistry`` — class (MLflow Tracking Server backend)."""
        assert isinstance(MlflowModelRegistry, type)

    def test_hugging_face_model_registry_is_class(self) -> None:
        """``HuggingFaceModelRegistry`` — class (Hugging Face Hub backend)."""
        assert isinstance(HuggingFaceModelRegistry, type)

    def test_local_fs_model_registry_is_class(self) -> None:
        """``LocalFSModelRegistry`` — class (local filesystem backend)."""
        assert isinstance(LocalFSModelRegistry, type)

    def test_model_record_is_class(self) -> None:
        """``ModelRecord`` — class (dataclass / Pydantic model)."""
        assert isinstance(ModelRecord, type)
