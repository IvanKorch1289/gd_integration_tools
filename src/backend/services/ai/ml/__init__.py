"""AI ML services — model loader, inference utilities."""

from __future__ import annotations as annotations

from src.backend.services.ai.ml.model_loader import (  # noqa: F401 — re-export
    MLModelLoader,
    get_ml_model_loader,
)

__all__ = ("MLModelLoader", "get_ml_model_loader")
