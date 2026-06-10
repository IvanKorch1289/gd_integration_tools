from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Page, Params

from src.backend.core.decorators.caching import response_cache
from src.backend.core.di.providers import get_cache_invalidator_provider
from src.backend.core.errors import NotFoundError, ServiceError
from src.backend.core.interfaces.db_model import DBModelProtocol
from src.backend.core.interfaces.repositories import RepositoryProtocol
from src.backend.core.logging import get_logger
from src.backend.dsl.codec.converters import transfer_model_to_schema
from src.backend.schemas.base import BaseSchema, PaginatedResult




def _is_orm_model(instance: Any) -> bool:
    cls = instance.__class__
    return hasattr(cls, "__tablename__") and hasattr(cls, "__table__")




class CacheMixin:
    """cache invalidation helper для BaseService. S61 W1 extraction."""

    __slots__ = ()

    async def _invalidate_entity_cache(self, *, entity_id: Any = None) -> None:
        """Инвалидирует кэш сущности после write-операции.

        Вызывает ``response_cache.invalidate_pattern`` (legacy) и
        ``CacheInvalidator.invalidate(tag, tag:id)`` — оба механизма
        работают параллельно (tag-based не мешает pattern-based).

        Args:
            entity_id: Идентификатор конкретной записи (опционально).
        """
        await response_cache.invalidate_pattern(pattern=self.__class__.__name__)

        tags = [self._entity_tag()]
        table_tag = self._table_tag()
        if table_tag:
            tags.append(table_tag)
        if entity_id is not None:
            tags.append(f"{self._entity_tag()}:{entity_id}")
        await get_cache_invalidator_provider().invalidate(*tags)

