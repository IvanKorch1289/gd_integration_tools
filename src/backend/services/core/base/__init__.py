"""BaseService package (S61 W1 decomp from base.py 526 LOC).

16 methods decomposed в 3 mixin files + helpers.py:
- ``cache_mixin.py`` (1): _invalidate_entity_cache
- ``crud_mixin.py`` (7): add, add_many, update, get, get_or_add, get_first_or_last_with_limit, delete
- ``versioning_mixin.py`` (4): get_all_object_versions, get_latest_object_version, restore_object_to_version, get_object_changes
- ``helpers.py``: 3 top-level funcs (_is_orm_model, get_service_for_model, create_service_class)

Core (4) остается в __init__.py: __init__, _service_error_boundary, _entity_tag, _table_tag.

Backward-compat: ``from src.backend.services.core.base import BaseService`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from contextlib import asynccontextmanager

from src.backend.core.errors import NotFoundError, ServiceError
from src.backend.schemas.base import BaseSchema


def _is_orm_model(instance: Any) -> bool:
    cls = instance.__class__
    return hasattr(cls, "__tablename__") and hasattr(cls, "__table__")


from src.backend.services.core.base.helpers import (
    _is_orm_model,  # S61 W1: re-export
    create_service_class,  # S61 W1: re-export
    get_service_for_model,  # S61 W1: re-export
)

__all__ = (
    "BaseService",
    "_is_orm_model",
    "create_service_class",
    "get_service_for_model",
)


class BaseService[
    ConcreteRepo,
    ConcreteResponseSchema: BaseSchema,
    ConcreteRequestSchema: BaseSchema,
    ConcreteVersionSchema: BaseSchema,
]:
    """Базовый сервис для работы с репозиториями.

    Предоставляет CRUD-операции, кэширование, версионирование.
    S61 W1 MRO: 3 mixins (cache/crud/versioning) + 4 core.
    """

    HelperMethods: type[Any]

    __slots__ = (
        "repo",
        "response_schema",
        "request_schema",
        "version_schema",
        "table_name",
        "helper",
    )

    def __init__(
        self,
        repo: type[ConcreteRepo] | None = None,
        response_schema: type[ConcreteResponseSchema] | None = None,
        request_schema: type[ConcreteRequestSchema] | None = None,
        version_schema: type[ConcreteVersionSchema] | None = None,
        table_name: str | None = None,
    ) -> None:
        """Инициализация сервиса.

        Args:
            repo: Репозиторий, связанный с сервисом.
            response_schema: Схема для преобразования данных.
            request_schema: Схема для валидации входных данных.
            version_schema: Схема для версий объекта.
            table_name: Опциональное имя таблицы для table-based cache invalidation.
                Если задано, генерируется дополнительный тег ``table:<table_name>``.
        """
        self.repo = repo
        self.response_schema = response_schema
        self.request_schema = request_schema
        self.version_schema = version_schema
        self.table_name = table_name
        self.helper = self.HelperMethods(repo)

    @asynccontextmanager
    async def _service_error_boundary(self):
        """Контекстный менеджер для единообразной обработки ошибок.

        Пробрасывает ``NotFoundError`` без изменений,
        остальные исключения оборачивает в ``ServiceError``.
        """
        try:
            yield
        except NotFoundError:
            raise
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError from exc

    def _entity_tag(self) -> str:
        """Возвращает tag-префикс для инвалидации кэша текущего сервиса.

        По умолчанию использует имя класса. Переопределите в наследниках,
        если хотите более короткий/осмысленный идентификатор сущности.
        """
        return f"entity:{self.__class__.__name__}"

    def _table_tag(self) -> str | None:
        """Возвращает table-based тег для инвалидации, если table_name задан."""
        if self.table_name:
            return f"table:{self.table_name}"
        return None
