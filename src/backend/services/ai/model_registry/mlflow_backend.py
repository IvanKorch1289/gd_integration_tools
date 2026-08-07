"""MLflow Tracking Server backend для AI Model Registry.

Wave: ``[wave:s8/k4-model-registry]``. Lazy-import ``mlflow``: модуль
импортируется без ``ai-model-registry`` extra; ImportError возникает
при первом использовании adapter'а.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from src.backend.services.ai.model_registry.adapter import (
    ModelRecord,
    ModelRegistryAdapter,
)

if TYPE_CHECKING:
    pass

from src.backend.core.logging import get_logger  # D-A1-04 fix (cycle 30)

__all__ = ("MlflowModelRegistry",)

_logger = get_logger("services.ai.model_registry.mlflow")


class MlflowModelRegistry(ModelRegistryAdapter):
    """Адаптер поверх MLflow Tracking Server.

    Args:
        tracking_uri: URI к MLflow серверу (``http://mlflow:5000`` или
            ``sqlite:///mlflow.db`` для локального hosting).
        registry_uri: Опц. отдельный URI реестра (если разделён с
            tracking).
    """

    def __init__(self, tracking_uri: str, *, registry_uri: str | None = None) -> None:
        self._tracking_uri = tracking_uri
        self._registry_uri = registry_uri
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from mlflow.tracking import MlflowClient
        except ImportError as exc:
            raise RuntimeError(
                "mlflow не установлен; добавьте extra ai-model-registry "
                "(uv sync --extra ai-model-registry)"
            ) from exc
        self._client = MlflowClient(
            tracking_uri=self._tracking_uri, registry_uri=self._registry_uri
        )
        return self._client

    @staticmethod
    def _mlflow_to_record(mv: Any) -> ModelRecord:
        """MLflow ModelVersion → ModelRecord."""
        tags = (
            {t.key: t.value for t in getattr(mv, "tags", [])}
            if hasattr(mv, "tags")
            else {}
        )
        return ModelRecord(
            name=str(getattr(mv, "name", "")),
            version=str(getattr(mv, "version", "1")),
            stage=str(getattr(mv, "current_stage", "None") or "None"),
            artifact_uri=getattr(mv, "source", None),
            tags=tags,
            description=getattr(mv, "description", None),
        )

    async def list_models(self) -> list[ModelRecord]:
        """Список всех registered models в MLflow registry."""
        client = self._ensure_client()
        loop = asyncio.get_running_loop()
        models = await loop.run_in_executor(
            None, lambda: client.search_registered_models()
        )
        records: list[ModelRecord] = []
        for m in models:
            latest = getattr(m, "latest_versions", None) or []
            for mv in latest:
                records.append(self._mlflow_to_record(mv))
        return records

    async def get_model(
        self, name: str, *, version: str | None = None, stage: str | None = None
    ) -> ModelRecord | None:
        """Получить model по ``name`` (+ optional version/stage)."""
        client = self._ensure_client()
        loop = asyncio.get_running_loop()

        if version is not None:
            mv = await loop.run_in_executor(
                None, lambda: client.get_model_version(name, version)
            )
            return self._mlflow_to_record(mv) if mv is not None else None

        # latest-by-stage (default "Production").
        stage_filter = stage or "Production"
        versions = await loop.run_in_executor(
            None, lambda: client.get_latest_versions(name, stages=[stage_filter])
        )
        return self._mlflow_to_record(versions[0]) if versions else None

    async def register_model(self, record: ModelRecord) -> ModelRecord:
        """Зарегистрировать новую model version в MLflow registry."""
        client = self._ensure_client()
        loop = asyncio.get_running_loop()

        # Ensure registered name exists.
        try:
            await loop.run_in_executor(
                None, lambda: client.create_registered_model(record.name)
            )
        except (ConnectionError, TimeoutError, RuntimeError) as _mlflow_exc:  # noqa: PERF203
            # D-A1-04 fix (cycle 30): narrow exceptions + debug logging.
            # Bare `except Exception: pass` маскировал MLflow backend failures
            # (e.g. registry down, timeout, name conflict).
            _logger.debug(
                "mlflow.create_registered_model.skipped",
                extra={"error": str(_mlflow_exc), "name": record.name},
            )

        artifact_uri = record.artifact_uri or "models:/placeholder"
        mv = await loop.run_in_executor(
            None,
            lambda: client.create_model_version(
                name=record.name, source=artifact_uri, description=record.description
            ),
        )
        # Применяем tags пакетно.
        for k, v in record.tags.items():
            await loop.run_in_executor(
                None,
                cast(
                    "Callable[[], Any]",
                    lambda key=k, val=v, mv_=mv: client.set_model_version_tag(
                        record.name, mv_.version, key, val
                    ),
                ),
            )
        return self._mlflow_to_record(mv)

    async def transition_stage(
        self, name: str, version: str, new_stage: str
    ) -> ModelRecord:
        """Перевести model в новый stage (Staging/Production/Archived)."""
        client = self._ensure_client()
        loop = asyncio.get_running_loop()
        mv = await loop.run_in_executor(
            None,
            lambda: client.transition_model_version_stage(
                name=name, version=version, stage=new_stage
            ),
        )
        return self._mlflow_to_record(mv)
