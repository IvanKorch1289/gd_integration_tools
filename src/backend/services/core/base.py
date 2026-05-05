import logging
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Page, Params

from src.core.decorators.caching import response_cache
from src.core.di.providers import get_cache_invalidator_provider
from src.core.errors import NotFoundError, ServiceError
from src.core.interfaces.db_model import DBModelProtocol
from src.core.interfaces.repositories import RepositoryProtocol
from src.schemas.base import BaseSchema, PaginatedResult
from src.utilities.converters import transfer_model_to_schema

logger = logging.getLogger(__name__)

__all__ = ("create_service_class", "BaseService", "get_service_for_model")


def _is_orm_model(instance: Any) -> bool:
    """Структурная проверка ORM-модели без зависимости от infrastructure.

    Проект использует SQLAlchemy DeclarativeBase: у любой модели есть
    атрибут ``__tablename__`` (через ``declared_attr``) и ``__table__``.
    Этого достаточно для duck-typing в сервисах.
    """
    cls = instance.__class__
    return hasattr(cls, "__tablename__") and hasattr(cls, "__table__")


class BaseService[
    ConcreteRepo,
    ConcreteResponseSchema: BaseSchema,
    ConcreteRequestSchema: BaseSchema,
    ConcreteVersionSchema: BaseSchema,
]:
    """Базовый сервис для работы с репозиториями.

    Предоставляет CRUD-операции, кэширование, версионирование
    и преобразование моделей в Pydantic-схемы.

    Attrs:
        repo: Репозиторий, связанный с сервисом.
        response_schema: Схема для преобразования данных ответа.
        request_schema: Схема для валидации входных данных.
        version_schema: Схема для преобразования версий.
    """

    @staticmethod
    @asynccontextmanager
    async def _service_error_boundary():
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

    class HelperMethods:
        """Вспомогательные методы для преобразования моделей в схемы."""

        def __init__(self, repo: Any) -> None:
            self.repo = repo

        async def _transfer(
            self,
            instance: Any,
            response_schema: type[BaseSchema],
            from_attributes: bool = True,
        ) -> BaseSchema | None:
            """Преобразует объект модели в схему ответа.

            Args:
                instance: Объект модели.
                response_schema: Целевая схема ответа.
                from_attributes: Преобразование связанных моделей.

            Returns:
                Схема ответа или ``None``.
            """
            if _is_orm_model(instance) or hasattr(instance.__class__, "version_parent"):
                return transfer_model_to_schema(  # type: ignore[return-value]
                    instance=instance,
                    schema=response_schema,
                    from_attributes=from_attributes,
                )
            return cast(BaseSchema | None, instance)

        async def _transfer_paginated(
            self, items: list[Any], response_schema: type[BaseSchema]
        ) -> list[BaseSchema | None]:
            """Преобразует список моделей в список схем."""
            return [await self._transfer(item, response_schema) for item in items]

        async def _process_and_transfer(
            self,
            repo_method: str,
            response_schema: type[BaseSchema],
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            """Вызывает метод репозитория и преобразует результат.

            Args:
                repo_method: Имя метода репозитория.
                response_schema: Целевая схема ответа.
                *args: Позиционные аргументы для метода.
                **kwargs: Именованные аргументы для метода.

            Returns:
                Результат в виде схемы, списка схем или
                ``PaginatedResult``.

            Raises:
                ServiceError: При ошибке репозитория.
            """
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

            except Exception as exc:
                raise ServiceError from exc

    def __init__(
        self,
        repo: type[ConcreteRepo] | None = None,
        response_schema: type[ConcreteResponseSchema] | None = None,
        request_schema: type[ConcreteRequestSchema] | None = None,
        version_schema: type[ConcreteVersionSchema] | None = None,
    ) -> None:
        """Инициализация сервиса.

        Args:
            repo: Репозиторий, связанный с сервисом.
            response_schema: Схема для преобразования данных.
            request_schema: Схема для валидации входных данных.
            version_schema: Схема для версий объекта.
        """
        self.repo = repo
        self.response_schema = response_schema
        self.request_schema = request_schema
        self.version_schema = version_schema
        self.helper = self.HelperMethods(repo)

    def _entity_tag(self) -> str:
        """Возвращает tag-префикс для инвалидации кэша текущего сервиса.

        По умолчанию использует имя класса. Переопределите в наследниках,
        если хотите более короткий/осмысленный идентификатор сущности.
        """
        return f"entity:{self.__class__.__name__}"

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
        if entity_id is not None:
            tags.append(f"{self._entity_tag()}:{entity_id}")
        await get_cache_invalidator_provider().invalidate(*tags)

    async def add(self, data: dict[str, Any]) -> ConcreteResponseSchema | None:
        """Добавляет объект и инвалидирует кэш.

        Args:
            data: Данные для создания объекта.

        Returns:
            Схема ответа или ``None``.
        """
        async with self._service_error_boundary():
            result: (
                ConcreteResponseSchema | None
            ) = await self.helper._process_and_transfer(
                "add", self.response_schema, data=data
            )
            entity_id = getattr(result, "id", None)
            await self._invalidate_entity_cache(entity_id=entity_id)
            return result

    async def add_many(
        self, data_list: list[dict[str, Any]]
    ) -> list[ConcreteResponseSchema | None]:
        """Добавляет несколько объектов.

        При ошибке элемент записывается как ``None``, ошибка
        логируется и сохраняется. После обработки всех элементов,
        если были ошибки, поднимается ``ServiceError`` с деталями.

        Args:
            data_list: Список данных для создания.

        Returns:
            Список схем ответа (``None`` для ошибочных элементов).

        Raises:
            ServiceError: Если хотя бы один элемент не был создан.
        """
        result: list[ConcreteResponseSchema | None] = []
        errors: list[dict[str, Any]] = []

        for idx, data in enumerate(data_list):
            try:
                response: ConcreteResponseSchema | None = await self.add(data=data)
                result.append(response)
            except Exception as exc:
                logger.exception(
                    "Ошибка при добавлении объекта #%d в add_many: %s", idx, data
                )
                result.append(None)
                errors.append({"index": idx, "data": data, "error": str(exc)})

        if errors:
            from src.core.errors import ServiceError

            raise ServiceError(
                detail=(
                    f"add_many: {len(errors)}/{len(data_list)} элементов не создано. "
                    f"Ошибки: {errors}"
                )
            )

        return result

    async def update(
        self, key: str, value: int, data: dict[str, Any]
    ) -> ConcreteResponseSchema | None:
        """Обновляет объект в репозитории.

        Args:
            key: Название поля.
            value: Значение поля.
            data: Данные для обновления.

        Returns:
            Обновлённая схема ответа или ``None``.
        """
        async with self._service_error_boundary():
            result = await self.helper._process_and_transfer(
                "update", self.response_schema, key=key, value=value, data=data
            )
            await self._invalidate_entity_cache(entity_id=value)
            return result

    @response_cache
    async def get(
        self,
        key: str | None = None,
        value: int | None = None,
        filter: Filter | None = None,
        pagination: Params | None = None,
        by: str = "id",
        order: str = "asc",
    ) -> (
        ConcreteResponseSchema
        | list[ConcreteResponseSchema]
        | Page[ConcreteResponseSchema]
        | None
    ):
        """Получает объекты по ключу, фильтру или все.

        Args:
            key: Название поля (опционально).
            value: Значение поля (опционально).
            filter: Фильтр для запроса (опционально).
            pagination: Параметры пагинации.
            by: Поле сортировки.
            order: Направление сортировки.

        Returns:
            Схема, список схем, ``Page`` или ``None``.
        """
        async with self._service_error_boundary():
            result = await self.helper._process_and_transfer(
                "get",
                self.response_schema,
                key=key,
                value=value,
                filter=filter,
                pagination=pagination,
                order=order,
                by=by,
            )

            if pagination:
                return Page.create(
                    items=result.items, total=result.total, params=pagination
                )
            return result

    async def get_or_add(
        self,
        key: str | None = None,
        value: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> ConcreteResponseSchema | None:
        """Получает объект или создаёт, если не найден.

        Args:
            key: Название поля.
            value: Значение поля.
            data: Данные для создания.

        Returns:
            Схема ответа или ``None``.
        """
        async with self._service_error_boundary():
            instance = None
            if key and value:
                instance = await self.helper._process_and_transfer(
                    "get", self.response_schema, key=key, value=value
                )
            if not instance and data:
                instance = await self.helper._process_and_transfer(
                    "add", self.response_schema, data=data
                )
            return instance

    @response_cache
    async def get_first_or_last_with_limit(
        self, limit: int = 1, by: str = "id", order: str = "asc"
    ) -> ConcreteResponseSchema | list[ConcreteResponseSchema] | None:
        """Возвращает первые/последние записи с лимитом."""
        async with self._service_error_boundary():
            return await self.helper._process_and_transfer(
                "first_or_last", self.response_schema, limit=limit, by=by, order=order
            )

    async def delete(self, key: str, value: int) -> None:
        """Удаляет объект и инвалидирует кэш.

        Args:
            key: Название поля.
            value: Значение поля.
        """
        async with self._service_error_boundary():
            await self.repo.delete(key=key, value=value)
            await self._invalidate_entity_cache(entity_id=value)

    @response_cache
    async def get_all_object_versions(
        self, object_id: int, order: str = "asc"
    ) -> list[BaseSchema | None]:
        """Получает все версии объекта.

        Args:
            object_id: ID объекта.
            order: Направление сортировки.

        Returns:
            Список версий в виде схем.
        """
        async with self._service_error_boundary():
            versions = await self.repo.get_all_versions(
                object_id=object_id, order=order
            )

            result: list[BaseSchema | None] = []
            for version in versions:
                try:
                    response = await self.helper._transfer(version, self.version_schema)
                    result.append(response)
                except Exception:
                    logger.exception(
                        "Ошибка преобразования версии object_id=%s", object_id
                    )

            return result

    @response_cache
    async def get_latest_object_version(self, object_id: int) -> BaseSchema | None:
        """Получает последнюю версию объекта.

        Args:
            object_id: ID объекта.

        Returns:
            Последняя версия или ``None``.
        """
        async with self._service_error_boundary():
            version = await self.repo.get_latest_version(object_id=object_id)
            return await self.helper._transfer(version, self.version_schema)

    async def restore_object_to_version(
        self, object_id: int, transaction_id: int
    ) -> BaseSchema | None:
        """Восстанавливает объект до указанной версии.

        Args:
            object_id: ID объекта.
            transaction_id: ID транзакции для восстановления.

        Returns:
            Восстановленный объект или ``None``.
        """
        async with self._service_error_boundary():
            restored_object = await self.repo.restore_to_version(
                object_id=object_id, transaction_id=transaction_id
            )
            return await self.helper._transfer(restored_object, self.response_schema)

    async def get_object_changes(self, object_id: int) -> list[dict[str, Any]]:
        """Получает список изменений атрибутов объекта.

        Args:
            object_id: ID объекта.

        Returns:
            Список изменений между версиями.
        """
        async with self._service_error_boundary():
            versions = await self.get_all_object_versions(object_id=object_id)
            if not versions:
                return []

            versions_dict = [
                (version.model_dump() if isinstance(version, BaseSchema) else version)
                for version in versions
            ]

            changes: list[dict[str, Any]] = []
            excluded_fields = {"transaction_id", "operation_type"}

            for i in range(1, len(versions_dict)):
                prev_version = versions_dict[i - 1]
                current_version = versions_dict[i]

                diff = {
                    attr: {
                        "old": prev_version.get(attr),
                        "new": current_version.get(attr),
                    }
                    for attr in prev_version.keys() | current_version.keys()
                    if attr not in excluded_fields
                    and prev_version.get(attr) != current_version.get(attr)
                }

                if diff:
                    changes.append(
                        {
                            "transaction_id": current_version.get("transaction_id"),
                            "operation_type": current_version.get("operation_type"),
                            "changes": diff,
                        }
                    )

            return changes


async def get_service_for_model(model: type[DBModelProtocol]) -> Any:
    """Возвращает сервис для указанной ORM-модели.

    Args:
        model: Класс ORM-модели (структурно — :class:`DBModelProtocol`).

    Returns:
        Класс сервиса.

    Raises:
        ValueError: Если сервис для модели не найден.
    """
    from importlib import import_module

    service_name = f"{model.__name__}Service"

    try:
        service_module = import_module(f"src.services.{model.__tablename__}")
        return getattr(service_module, service_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"Сервис для модели {model.__name__} не найден: {exc}"
        ) from exc


def create_service_class(
    request_schema: type[BaseSchema],
    response_schema: type[BaseSchema],
    version_schema: type[BaseSchema],
    repo: type[RepositoryProtocol],
) -> BaseService:
    """Фабрика для создания экземпляра BaseService."""
    return BaseService(repo, response_schema, request_schema, version_schema)
