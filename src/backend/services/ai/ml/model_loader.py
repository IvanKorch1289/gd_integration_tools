"""ML Model Loader — универсальный lazy-loading для torch / sklearn / CatBoost / LightGBM.

Wave: ``[wave:s29/local-models-repository]``.

LRU cache предотвращает повторную загрузку одной и той же модели.
Graceful fallback если библиотека не установлена.

Реализует :class:`MLModelLoaderProtocol` из ``core.interfaces.ml_model_loader``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any

from src.backend.core.interfaces.ml_model_loader import (
    MLModelLoaderProtocol,
    MLModelType,
)

__all__ = ("MLModelLoader",)

logger = logging.getLogger(__name__)

# Module-level singleton instance for process lifetime
_loader_instance: MLModelLoaderProtocol | None = None


def get_ml_model_loader() -> MLModelLoaderProtocol:
    """Возвращает глобальный синглтон MLModelLoader.

    Используется процессором ml_predict для DI-free доступа к loader.
    """
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = MLModelLoader(max_models=8)
    return _loader_instance


class MLModelLoader:
    """Универсальный загрузчик ML-моделей с LRU-кэшированием.

    Потокобезопасный синглтон: загружает модель один раз, повторные вызовы
    возвращают закэшированный экземпляр. Вытеснение по LRU при превышении
    ``max_models``.

    Реализует :class:`MLModelLoaderProtocol`.

    Args:
        max_models: Максимальное число моделей в кэше (default 8).
    """

    _MAX_MODELS: int = 8

    def __init__(self, max_models: int = 8) -> None:
        self._max_models = max_models
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._lock = Lock()

    # ── MLModelLoaderProtocol implementation ──────────────────────────────────

    async def load(
        self, path: str | Path, model_type: MLModelType | None = None
    ) -> Any:
        """Загружает модель (lazy, с LRU-кэшированием)."""
        path_str = str(Path(path).resolve())
        cache_key = f"{path_str}:{model_type or 'auto'}"

        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

        loop = asyncio.get_running_loop()
        model = await loop.run_in_executor(None, self._load_sync, path, model_type)

        with self._lock:
            self._cache[cache_key] = model
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self._max_models:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.info("MLModelLoader LRU evicted: %s", evicted_key)

        return model

    def unload(self, path: str | Path) -> None:
        """Удаляет модель из кэша (освобождает память)."""
        path_str = str(Path(path).resolve())
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(path_str)]
            for key in keys_to_remove:
                del self._cache[key]
                logger.info("MLModelLoader unloaded: %s", key)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_sync(self, path: str | Path, model_type: MLModelType | None) -> Any:
        """Синхронная загрузка (вызывается в executor)."""
        resolved = Path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"Model file not found: {resolved}")

        detected = model_type or self._detect_type(resolved)
        if detected is None:
            raise RuntimeError(
                f"Cannot detect model type for {resolved}; "
                "please specify model_type explicitly"
            )

        return self._load_by_type(resolved, detected)

    def _detect_type(self, path: Path) -> MLModelType | None:
        """Определяет тип модели по расширению файла."""
        suffix = path.suffix.lower()
        mapping: dict[str, MLModelType] = {
            ".pt": "torch",
            ".pth": "torch",
            ".jit.pt": "torchscript",
            ".onnx": "onnx",
            ".joblib": "sklearn",
            ".pkl": "joblib",
            ".pkl.gz": "joblib",
            ".cbm": "catboost",
            ".mb": "lightgbm",
        }
        return mapping.get(suffix)

    def _load_by_type(self, path: Path, model_type: MLModelType) -> Any:
        """Загрузка модели конкретного типа."""
        if model_type == "torch":
            return self._load_torch(path)
        if model_type == "torchscript":
            return self._load_torchscript(path)
        if model_type == "onnx":
            return self._load_onnx(path)
        if model_type == "sklearn":
            return self._load_sklearn(path)
        if model_type == "catboost":
            return self._load_catboost(path)
        if model_type == "lightgbm":
            return self._load_lightgbm(path)
        if model_type == "joblib":
            return self._load_joblib(path)
        raise RuntimeError(f"Unsupported model type: {model_type}")

    def _load_torch(self, path: Path) -> Any:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "torch не установлен; установите: uv add torch "
                "(или используйте CPU-only: uv add torch --index-url https://download.pytorch.org/whl/cpu)"
            ) from exc
        # SECURITY (ADR-SEC-001 Option A): fail-fast if weights_only=True
        # does not work. Accepting arbitrary code-execution risk via
        # weights_only=False was removed. The workspace mount-path restriction
        # (V22 RLS, AI_WORKSPACE=/ai-models/) is still respected upstream.
        try:
            return torch.load(path, map_location="cpu", weights_only=True)
        except Exception as exc:
            raise RuntimeError(
                f"torch.load(weights_only=True) failed for {path}. "
                "Model may contain pickled code — refusing to load with "
                "weights_only=False for security reasons (ADR-SEC-001)."
            ) from exc

    def _load_torchscript(self, path: Path) -> Any:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("torch не установлен") from exc
        return torch.jit.load(path, map_location="cpu")

    def _load_onnx(self, path: Path) -> Any:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "onnxruntime не установлен; установите: uv add onnxruntime"
            ) from exc
        return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])

    def _load_sklearn(self, path: Path) -> Any:
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError(
                "scikit-learn не установлен; установите: uv add scikit-learn"
            ) from exc
        # S301: joblib.load аналогичен pickle; допустимо из AI_WORKSPACE (изолирован)
        return joblib.load(path)

    def _load_catboost(self, path: Path) -> Any:
        try:
            from catboost import CatBoostClassifier, CatBoostRegressor
        except ImportError as exc:
            raise RuntimeError(
                "catboost не установлен; установите: uv add catboost"
            ) from exc
        # CatBoost сохраняет .cbm файлы (CatBoost Model)
        # Может быть классификатор или регрессор — попробуем оба
        # S301: CatBoost .cbm — бинарный формат без pickle-опасности
        for cls in (CatBoostClassifier, CatBoostRegressor):
            try:
                return cls().load_model(str(path))
            except Exception as exc:
                logger.debug("CatBoost load attempt failed for %s: %s", path, exc)
                continue
        raise RuntimeError(f"Cannot load {path} as CatBoost model")

    def _load_lightgbm(self, path: Path) -> Any:
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError(
                "lightgbm не установлен; установите: uv add lightgbm"
            ) from exc
        return lgb.Booster(model_file=str(path))

    def _load_joblib(self, path: Path) -> Any:
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError(
                "joblib не установлен; установите: uv add joblib"
            ) from exc
        return joblib.load(path)
