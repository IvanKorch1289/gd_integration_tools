"""AI Model Registry — MLflow + Hugging Face Hub adapters.

Wave: ``[wave:s8/k4-model-registry]``. Public API:

* :class:`ModelRegistryAdapter` — Protocol для backend-агностичного
  доступа к реестру моделей.
* :class:`MlflowModelRegistry` — MLflow Tracking Server backend.
* :class:`HuggingFaceModelRegistry` — Hugging Face Hub backend.
* :class:`ModelRecord` — доменная запись модели в реестре.
"""

from __future__ import annotations

from src.backend.services.ai.model_registry.adapter import (
    ModelRecord,
    ModelRegistryAdapter,
)
from src.backend.services.ai.model_registry.hf_hub_backend import (
    HuggingFaceModelRegistry,
)
from src.backend.services.ai.model_registry.local_fs_backend import LocalFSModelRegistry
from src.backend.services.ai.model_registry.mlflow_backend import MlflowModelRegistry

__all__ = (
    "ModelRecord",
    "ModelRegistryAdapter",
    "MlflowModelRegistry",
    "HuggingFaceModelRegistry",
    "LocalFSModelRegistry",
)
