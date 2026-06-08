"""Composite Model Registry — объединяет MLflow + HF Hub + Local FS (Sprint 11 K4 W6 + S29).

Делегирует list_models() во все backends и сводит результаты по
(name, version, backend) — позволяет UI показывать модели из любых
источников в одном списке. Запись (register_model) идёт в указанный
provider, по умолчанию — первый из списка (mlflow). Local FS — lowest
priority read-only backend.
"""

from __future__ import annotations

from src.backend.infrastructure.logging.factory import get_logger
from src.backend.services.ai.model_registry.adapter import (
    ModelRecord,
    ModelRegistryAdapter,
)

__all__ = ("CompositeModelRegistry",)

logger = get_logger("services.ai.model_registry.composite")


class CompositeModelRegistry:
    """Чтение из нескольких backends + запись в primary."""

    def __init__(self, backends: dict[str, ModelRegistryAdapter]) -> None:
        """Args:
        backends: Словарь ``backend_id -> adapter`` (mlflow/huggingface/...).
        """
        if not backends:
            raise ValueError("CompositeModelRegistry requires at least one backend")
        self._backends = backends
        self._primary = next(iter(backends.keys()))

    @property
    def primary(self) -> str:
        """Backend, используемый для write-операций по умолчанию."""
        return self._primary

    def with_primary(self, backend_id: str) -> CompositeModelRegistry:
        """Создать новый Composite с другим primary backend."""
        if backend_id not in self._backends:
            raise KeyError(backend_id)
        new = CompositeModelRegistry(self._backends)
        new._primary = backend_id
        return new

    async def list_models(self) -> list[ModelRecord]:
        """Слить list_models() из всех backends.

        Дубликаты по ``(name, version)`` — не дедупим (разные backend'ы
        могут хостить одну и ту же модель с разными артефактами).
        Поле ``extra["backend"]`` помечает источник.
        """
        out: list[ModelRecord] = []
        for backend_id, adapter in self._backends.items():
            try:
                models = await adapter.list_models()
                for m in models:
                    m_extra = dict(m.extra)
                    m_extra.setdefault("backend", backend_id)
                    out.append(m.model_copy(update={"extra": m_extra}))
            except Exception as exc:
                logger.warning(
                    "Composite list_models: backend=%s failed: %s", backend_id, exc
                )
        return out

    async def get_model(
        self,
        name: str,
        *,
        version: str | None = None,
        stage: str | None = None,
        backend: str | None = None,
    ) -> ModelRecord | None:
        """Поиск модели; если указан backend — только в нём, иначе во всех."""
        targets = (
            [backend] if backend and backend in self._backends else list(self._backends)
        )
        for backend_id in targets:
            adapter = self._backends[backend_id]
            try:
                m = await adapter.get_model(name, version=version, stage=stage)
                if m is not None:
                    m_extra = dict(m.extra)
                    m_extra.setdefault("backend", backend_id)
                    return m.model_copy(update={"extra": m_extra})
            except Exception as exc:
                logger.warning("get_model backend=%s: %s", backend_id, exc)
        return None

    async def register_model(
        self, record: ModelRecord, *, backend: str | None = None
    ) -> ModelRecord:
        """Запись в указанный (или primary) backend."""
        backend_id = backend or self._primary
        if backend_id not in self._backends:
            raise KeyError(backend_id)
        adapter = self._backends[backend_id]
        result = await adapter.register_model(record)
        result_extra = dict(result.extra)
        result_extra.setdefault("backend", backend_id)
        return result.model_copy(update={"extra": result_extra})

    async def transition_stage(
        self, name: str, version: str, new_stage: str, *, backend: str | None = None
    ) -> ModelRecord:
        """Перевод в новый stage в указанном backend (default primary)."""
        backend_id = backend or self._primary
        adapter = self._backends[backend_id]
        result = await adapter.transition_stage(name, version, new_stage)
        result_extra = dict(result.extra)
        result_extra.setdefault("backend", backend_id)
        return result.model_copy(update={"extra": result_extra})

    def backend_ids(self) -> list[str]:
        """Возвращает список зарегистрированных backend ids."""
        return list(self._backends.keys())
