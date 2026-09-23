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

from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any

if TYPE_CHECKING:
    pass

from contextlib import asynccontextmanager as asynccontextmanager

from src.backend.core.errors import NotFoundError as NotFoundError
from src.backend.core.errors import ServiceError as ServiceError
from src.backend.core.utils.converters import (  # noqa: F401 — re-export
    transfer_model_to_schema as transfer_model_to_schema,
)
from src.backend.schemas.base import BaseSchema as BaseSchema
from src.backend.schemas.base import PaginatedResult as PaginatedResult


def _is_orm_model(instance: Any) -> bool:
    cls = instance.__class__
    return hasattr(cls, "__tablename__") and hasattr(cls, "__table__")


from src.backend.services.core.base.cache_mixin import (  # noqa: F401 — re-export
    CacheMixin,  # S61 W1: MRO as CacheMixin  # S61 W1: MRO
)
from src.backend.services.core.base.crud_mixin import (  # noqa: F401 — re-export
    CrudMixin,  # S61 W1: MRO as CrudMixin  # S61 W1: MRO
)
from src.backend.services.core.base.helpers import (  # noqa: F401 — re-export
    _is_orm_model,  # S61 W1: re-export
    create_service_class,  # S61 W1: re-export
    get_service_for_model,  # S61 W1: re-export
)
from src.backend.services.core.base.versioning_mixin import (  # noqa: F401 — re-export
    VersioningMixin,  # S61 W1: MRO
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
](CrudMixin, CacheMixin, VersioningMixin):
    """Базовый сервис для работы с репозиториями.

    Предоставляет CRUD-операции, кэширование, версионирование.
    S61 W1 MRO: 3 mixins (cache/crud/versioning) + 4 core.
    """

    HelperMethods: type[Any]

    __slots__ = (
        "helper",
        "repo",
        "request_schema",
        "response_schema",
        "table_name",
        "version_schema",
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
        # G4-хвост fix (2026-09-14): восстановлен СОБСТВЕННЫЙ HelperMethods
        # (S61 потерял его: self.helper переприназначали на repo.helper,
        # у которого нет _transfer/_process_and_transfer → все write-CRUD
        # сервисов падали AttributeError→ServiceError).
        self.helper = BaseService.ServiceHelper(repo) if repo is not None else None  # type: ignore[attr-defined]

    class ServiceHelper:
        """Преобразование ORM-моделей в схемы + вызов repo-методов по имени.

        Восстановлен из pre-S61 BaseService (2026-09-14): CrudMixin и
        VersioningMixin вызывают helper._process_and_transfer/_transfer.
        """

        def __init__(self, repo: Any) -> None:
            self.repo = repo

        async def _transfer(
            self,
            instance: Any,
            response_schema: type[BaseSchema],
            from_attributes: bool = True,
        ) -> BaseSchema | None:
            """ORM-модель → схема ответа (не-ORM проходит как есть)."""
            cls = instance.__class__
            is_orm = hasattr(cls, "__tablename__") and hasattr(cls, "__table__")
            if is_orm or hasattr(instance.__class__, "version_parent"):
                return transfer_model_to_schema(  # type: ignore[return-value]
                    instance=instance,
                    schema=response_schema,
                    from_attributes=from_attributes,
                )
            from typing import cast

            return cast(BaseSchema | None, instance)

        async def _transfer_paginated(
            self, items: list[Any], response_schema: type[BaseSchema]
        ) -> list[BaseSchema | None]:
            """Список моделей → список схем."""
            return [await self._transfer(item, response_schema) for item in items]

        async def _process_and_transfer(
            self,
            repo_method: str,
            response_schema: type[BaseSchema],
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            """Вызвать repo-метод по имени и преобразовать результат в схемы."""
            try:
                instance = await getattr(self.repo, repo_method)(*args, **kwargs)

                if isinstance(instance, dict) and "items" in instance:
                    items = await self._transfer_paginated(
                        instance["items"], response_schema
                    )
                    return PaginatedResult(items=items, total=instance["total"])

                if not instance:
                    return []

                if isinstance(instance, list):
                    return [
                        await self._transfer(item, response_schema) for item in instance
                    ]

                return await self._transfer(instance, response_schema)
            except ServiceError:
                raise
            except Exception as exc:
                raise ServiceError from exc

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
