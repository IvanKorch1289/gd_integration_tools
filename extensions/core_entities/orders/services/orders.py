"""Сервис Order (миграция из ядра — Sprint 7, R-V15-16).

Каноническое расположение в V11 plugin layout. Старый модуль
``src.backend.services.core.orders`` сохраняется как backward-compat
shim и эмитит DeprecationWarning.

Полная бизнес-логика (CRUD + интеграция с СКБ-Техно + S3 + ES) пока
остаётся в shim-модуле, чтобы не разрушать существующие callsite'ы.
Этот модуль предоставляет re-export ``OrderService`` и
``get_order_service``, опираясь на канонические репозиторий и кэш
из ``extensions.core_entities.orders.repositories``.
"""

from __future__ import annotations

from typing import Any

import pydash
from pydantic import BaseModel

from extensions.core_entities.orders.repositories.orders import get_order_repo
from src.backend.core.decorators.caching import response_cache
from src.backend.core.di.module_registry import resolve_module
from src.backend.core.errors import NotFoundError
from src.backend.core.interfaces.order_storage import OrderStorageProtocol
from src.backend.core.interfaces.repositories import (
    FileRepositoryProtocol,
    OrderRepositoryProtocol,
)
from src.backend.schemas.base import BaseSchema
from src.backend.schemas.route_schemas.orders import (
    OrderSchemaIn,
    OrderSchemaOut,
    OrderVersionSchemaOut,
)
from src.backend.services.core.base import BaseService
from src.backend.services.integrations.skb import APISKBService, get_skb_service

__all__ = ("OrderService", "get_order_service")


class OrderService(
    BaseService[
        OrderRepositoryProtocol,
        OrderSchemaOut,
        OrderSchemaIn,
        OrderVersionSchemaOut,
    ]
):
    """Сервис заказов (CRUD + интеграции).

    Полный набор поведений (СКБ-Техно, S3, ES-индексация) — в shim'е
    ``src.backend.services.core.orders``, который этот класс просто
    оборачивает. После завершения миграции БД-моделей и индексов
    полная логика переедет сюда (Sprint 8 follow-up).
    """

    def __init__(
        self,
        schema_in: type[BaseModel],
        schema_out: type[BaseModel],
        version_schema: type[BaseModel],
        repo: OrderRepositoryProtocol,
        file_repo: FileRepositoryProtocol,
        request_service: APISKBService,
        s3_service: OrderStorageProtocol,
    ) -> None:
        super().__init__(
            repo=repo,
            request_schema=schema_in,
            response_schema=schema_out,
            version_schema=version_schema,
        )
        self.file_repo = file_repo
        self.request_service = request_service
        self.s3_service = s3_service

    async def _get_order_data(self, order_id: int) -> dict[str, Any]:
        """Читает заказ и сериализует в dict (для downstream обработки)."""
        order = await self.get(key="id", value=order_id)
        if not order:
            raise NotFoundError("Заказ не найден")
        return order.model_dump() if isinstance(order, BaseSchema) else order

    async def _get_order_files(self, order_data: dict[str, Any]) -> list[str]:
        """Возвращает список UUID файлов заказа."""
        return [
            str(file_data["object_uuid"])
            for file_data in order_data.get("files", [])
        ]

    async def _invalidate_cache(self) -> None:
        """Инвалидирует кэш по имени сервиса."""
        await response_cache.invalidate_pattern(pattern=self.__class__.__name__)


_order_service_instance: OrderService | None = None


def get_order_service() -> OrderService:
    """Возвращает singleton экземпляр :class:`OrderService`.

    Полный wiring (file_repo + s3_service) делает legacy-фабрика из
    shim'а ``src.backend.services.core.orders.get_order_service``,
    после стабилизации миграции она будет перенесена сюда. Сейчас —
    re-export, чтобы извлекать через каноническое имя.
    """
    global _order_service_instance
    if _order_service_instance is None:
        legacy = resolve_module("services.core.orders").get_order_service()
        _order_service_instance = legacy
    return _order_service_instance


__legacy_pydash_anchor__ = pydash  # сохраняет совместимость с legacy-импортом
