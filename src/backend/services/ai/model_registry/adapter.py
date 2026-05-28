"""Protocol + Pydantic domain-модель для AI Model Registry.

Wave: ``[wave:s8/k4-model-registry]``.

Контракт: backend-агностичный доступ к версионированному реестру моделей.
Поддерживаемые backends — MLflow (см. ``mlflow_backend.py``) и
Hugging Face Hub (см. ``hf_hub_backend.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("ModelRecord", "ModelRegistryAdapter")


class ModelRecord(BaseModel):
    """Метаданные одной версии модели в реестре.

    Атрибуты:
        name: Имя модели (``credit-scoring-llm``).
        version: SemVer / numeric версия.
        stage: ``"Production"`` / ``"Staging"`` / ``"Archived"`` / ``"None"``.
        artifact_uri: URI к артефактам (``s3://...``, ``hf://...``).
        tags: Произвольные key-value метки (``framework``, ``training_run``).
        description: Свободный текст.
        created_at: Время создания записи.
        updated_at: Время последнего обновления.
    """

    model_config = ConfigDict(extra="ignore", frozen=False)

    name: str
    version: str = Field(default="1")
    stage: Literal["None", "Staging", "Production", "Archived"] = Field(default="None")
    artifact_uri: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    # ── W2: capability-tags для dynamic routing ──────────────────────────
    capability_tags: dict[str, bool] = Field(default_factory=dict)
    latency_tier: Literal["fast", "standard", "slow"] = Field(default="standard")
    max_tokens: int = Field(default=4096)
    supports_vision: bool = Field(default=False)
    supports_function_calling: bool = Field(default=False)
    supports_streaming: bool = Field(default=False)

    def match_capabilities(
        self,
        *,
        vision: bool | None = None,
        function_calling: bool | None = None,
        streaming: bool | None = None,
        min_max_tokens: int | None = None,
        latency_tier: str | None = None,
    ) -> bool:
        """Проверяет, удовлетворяет ли модель заданным capability-требованиям.

        Фильтрация работает как subset-	match: если модель поддерживает
        capability — она проходит фильтр. ``capability=False`` означает
        "не требуется", а не "требуется отсутствие".
        """
        if vision is not None and not self.supports_vision:
            return False
        if function_calling is not None and not self.supports_function_calling:
            return False
        if streaming is not None and not self.supports_streaming:
            return False
        if min_max_tokens is not None and self.max_tokens < min_max_tokens:
            return False
        if latency_tier is not None and self.latency_tier != latency_tier:
            return False
        return True


@runtime_checkable
class ModelRegistryAdapter(Protocol):
    """Контракт реестра моделей.

    Каждый метод lazy — реализации могут блокировать на сетевом вызове;
    вся работа сервиса должна оборачиваться ``run_in_executor`` если
    backend синхронный (mlflow / huggingface_hub).
    """

    async def list_models(self) -> list[ModelRecord]:
        """Все зарегистрированные модели."""
        ...

    async def get_model(
        self, name: str, *, version: str | None = None, stage: str | None = None
    ) -> ModelRecord | None:
        """Конкретная версия / stage модели.

        Если ``version`` и ``stage`` не заданы — возвращается latest
        production-версия (или None если её нет).
        """
        ...

    async def register_model(self, record: ModelRecord) -> ModelRecord:
        """Регистрирует новую версию модели."""
        ...

    async def transition_stage(
        self, name: str, version: str, new_stage: str
    ) -> ModelRecord:
        """Переводит версию в новый stage (``Staging`` → ``Production``)."""
        ...
