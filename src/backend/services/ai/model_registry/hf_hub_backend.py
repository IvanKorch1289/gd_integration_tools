"""Hugging Face Hub backend для AI Model Registry.

Wave: ``[wave:s8/k4-model-registry]``. Read-only поверх public HF Hub;
upload в registry через HF выполняется отдельным flow (HuggingFace CLI),
``register_model`` ограничен созданием repo + tag'ов через
``huggingface_hub.HfApi``.

Hugging Face Hub не имеет понятия stage (Production/Staging) — оно
эмулируется через tag ``stage:Production`` на model card.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.backend.services.ai.model_registry.adapter import (
    ModelRecord,
    ModelRegistryAdapter,
)

__all__ = ("HuggingFaceModelRegistry",)

_logger = logging.getLogger(__name__)


class HuggingFaceModelRegistry(ModelRegistryAdapter):
    """Адаптер поверх Hugging Face Hub.

    Args:
        token: HF API token (``HF_TOKEN`` env). Анонимный режим (None) —
            только read public models.
        organization: Опц. фильтр по namespace ``<org>/...``.
    """

    def __init__(
        self, *, token: str | None = None, organization: str | None = None
    ) -> None:
        self._token = token
        self._organization = organization
        self._api: Any = None

    def _ensure_api(self) -> Any:
        if self._api is not None:
            return self._api
        try:
            from huggingface_hub import HfApi
        except ImportError as exc:
            raise RuntimeError(
                "huggingface_hub не установлен; добавьте extra "
                "ai-model-registry (uv sync --extra ai-model-registry)"
            ) from exc
        self._api = HfApi(token=self._token)
        return self._api

    @staticmethod
    def _hf_to_record(model_info: Any) -> ModelRecord:
        """HF ModelInfo → ModelRecord."""
        tags_list = getattr(model_info, "tags", []) or []
        tags = {}
        stage = "None"
        for t in tags_list:
            if isinstance(t, str) and t.startswith("stage:"):
                stage = t.split(":", 1)[1]
            elif isinstance(t, str) and ":" in t:
                k, v = t.split(":", 1)
                tags[k.strip()] = v.strip()
        return ModelRecord(
            name=str(getattr(model_info, "modelId", getattr(model_info, "id", ""))),
            version=str(getattr(model_info, "sha", "main") or "main"),
            stage=stage
            if stage in {"None", "Staging", "Production", "Archived"}
            else "None",
            artifact_uri=f"hf://{getattr(model_info, 'modelId', getattr(model_info, 'id', ''))}",
            tags=tags,
            description=getattr(model_info, "description", None),
        )

    async def list_models(self) -> list[ModelRecord]:
        api = self._ensure_api()
        loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {"limit": 100}
        if self._organization:
            kwargs["author"] = self._organization
        models = await loop.run_in_executor(
            None, lambda: list(api.list_models(**kwargs))
        )
        return [self._hf_to_record(m) for m in models]

    async def get_model(
        self, name: str, *, version: str | None = None, stage: str | None = None
    ) -> ModelRecord | None:
        api = self._ensure_api()
        loop = asyncio.get_running_loop()
        try:
            info = await loop.run_in_executor(
                None, lambda: api.model_info(repo_id=name, revision=version or "main")
            )
        except Exception as exc:
            _logger.info("HF Hub model_info(%s) → not found: %s", name, exc)
            return None
        return self._hf_to_record(info)

    async def register_model(self, record: ModelRecord) -> ModelRecord:
        """Создаёт repo в HF Hub.

        Загрузка артефактов — отдельный flow (`huggingface-cli upload`);
        register_model только создаёт mета-запись.
        """
        api = self._ensure_api()
        loop = asyncio.get_running_loop()
        repo_id = record.name
        await loop.run_in_executor(
            None,
            lambda: api.create_repo(
                repo_id=repo_id, repo_type="model", exist_ok=True, private=False
            ),
        )
        return await self.get_model(repo_id) or record

    async def transition_stage(
        self, name: str, version: str, new_stage: str
    ) -> ModelRecord:
        """Эмулирует stage через tag ``stage:<new_stage>`` на model card.

        В реальной интеграции это требует обновления README.md model card
        с YAML front-matter ``tags: [stage:Production]`` — выходит за
        scope adapter'а; здесь возвращаем merged record без сетевой
        записи (best-effort no-op).
        """
        current = await self.get_model(name, version=version)
        if current is None:
            raise RuntimeError(f"HF Hub: model {name}/{version} не найден")
        current.stage = new_stage
        return current
