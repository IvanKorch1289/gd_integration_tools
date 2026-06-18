"""Admin REST для AI Model Registry (Sprint 11 K4 W6).

* ``GET /admin/model-registry/models`` — composite list (MLflow + HF Hub).
* ``GET /admin/model-registry/models/{name}`` — конкретная модель.
* ``POST /admin/model-registry/models/{name}/use-in-route`` — генерирует
  DSL snippet ``.llm_call(provider=..., model=...)``.

Guard: feature_flags.ai_model_registry_ui (404 если OFF).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from src.backend.core.config.features import feature_flags

router = APIRouter(prefix="/admin/model-registry", tags=["admin", "model_registry"])


def _guard_enabled() -> None:
    if not feature_flags.ai_model_registry_ui:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ai_model_registry_ui feature disabled",
        )


async def _composite() -> Any:
    """Lazy factory composite registry — DI-binding делается в lifespan."""
    from src.backend.services.ai.model_registry.composite import CompositeModelRegistry

    backends: dict[str, Any] = {}
    try:
        from src.backend.services.ai.model_registry.mlflow_backend import (
            MlflowModelRegistry,
        )

        backends["mlflow"] = MlflowModelRegistry()
    except Exception as _:
        pass
    try:
        from src.backend.services.ai.model_registry.hf_hub_backend import (
            HuggingFaceModelRegistry,
        )

        backends["huggingface"] = HuggingFaceModelRegistry()
    except Exception as _:
        pass

    if not backends:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no backends available (mlflow/huggingface_hub not installed)",
        )
    return CompositeModelRegistry(backends)


@router.get(
    "/models",
    summary="Composite-список AI моделей из всех backends",
    description=(
        "Возвращает список моделей из всех зарегистрированных "
        "model registry backends (MLflow, HuggingFace Hub). "
        "Требует feature-flag ai_model_registry_ui. "
        "Возвращает 404 если feature OFF, 503 если ни один backend "
        "не доступен."
    ),
    tags=["admin", "model_registry"],
    responses={
        200: {"description": "Composite list моделей + backend ids."},
        404: {"description": "feature_flag ai_model_registry_ui = OFF."},
        503: {"description": "Ни один backend не доступен."},
    },
)
async def list_models() -> dict[str, Any]:
    """Composite-список моделей из всех зарегистрированных backends."""
    _guard_enabled()
    registry = await _composite()
    models = await registry.list_models()
    return {
        "models": [m.model_dump() for m in models],
        "backends": registry.backend_ids(),
        "count": len(models),
    }


@router.get(
    "/models/{name}",
    summary="Конкретная AI модель по имени",
    description=(
        "Возвращает детали конкретной модели по name. "
        "Опциональный query param version (latest production если None). "
        "404 если feature_flag OFF или model not found."
    ),
    tags=["admin", "model_registry"],
    responses={
        200: {"description": "Model details (name, version, metadata)."},
        404: {"description": "feature OFF или model not found."},
        503: {"description": "Backend недоступен."},
    },
)
async def get_model(name: str, version: str | None = None) -> dict[str, Any]:
    """Конкретная версия модели (или latest production)."""
    _guard_enabled()
    registry = await _composite()
    model = await registry.get_model(name, version=version)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"model {name} not found"
        )
    return model.model_dump()


@router.post(
    "/models/{name}/use-in-route",
    summary="Генерирует DSL snippet для использования модели в route",
    description=(
        "Генерирует готовый DSL snippet ``.llm_call(provider=..., model=...)`` "
        "для указанной модели. Используется в Admin UI для copy-paste "
        "готового DSL вызова в route definition. "
        "404 если feature OFF или model not found."
    ),
    tags=["admin", "model_registry"],
    responses={
        200: {"description": "Model info + DSL snippet для вставки в route."},
        404: {"description": "feature OFF или model not found."},
        503: {"description": "Backend недоступен."},
    },
)
async def use_in_route(name: str, version: str | None = None) -> dict[str, Any]:
    """Сгенерировать DSL snippet для .llm_call с этой моделью."""
    _guard_enabled()
    registry = await _composite()
    model = await registry.get_model(name, version=version)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"model {name} not found"
        )
    provider = model.extra.get("backend", "huggingface")
    model_ref = f"{model.name}@{model.version}"
    snippet = (
        f'.llm_call(provider="{provider}", model="{model_ref}", '
        f'system_prompt="Use {model.name} model")'
    )
    return {
        "name": model.name,
        "version": model.version,
        "provider": provider,
        "snippet": snippet,
    }
