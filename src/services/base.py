import logging
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Page, Params

from app.core.decorators.caching import response_cache
from app.core.errors import NotFoundError, ServiceError
from app.infrastructure.db.models.base import BaseModel
from app.infrastructure.repositories.base import SQLAlchemyRepository
from app.schemas.base import BaseSchema, PaginatedResult
from app.utilities.utils import utilities

logger = logging.getLogger(__name__)

__all__ = ("create_service_class", "BaseService", "get_service_for_model")


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
            if isinstance(instance, BaseModel) or hasattr(
                instance.__class__, "version_parent"
            ):
                return utilities.transfer_model_to_schema(  # type: ignore[return-value]
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
            self, repo_method: str, response_schema: type[BaseSchema], *args: Any, **kwargs: Any
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
                        await self._transfer(item, response_schema)
                        for item in instance
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

    async def add(self, data: dict[str, Any]) -> ConcreteResponseSchema | None:
        """Добавляет объект и инвалидирует кэш.

        Args:
            data: Данные для создания объекта.

        Returns:
            Схема ответа или ``None``.
        """
        async with self._service_error_boundary():
            result: ConcreteResponseSchema | None = (
                await self.helper._process_and_transfer(
                    "add", self.response_schema, data=data
                )
            )
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )
            return result

    async def add_many(
        self, data_list: list[dict[str, Any]]
    ) -> list[ConcreteResponseSchema | None]:
        """Добавляет несколько объектов.

        Args:
            data_list: Список данных для создания.

        Returns:
            Список схем ответа (ошибочные элементы
            пропускаются с логированием).
        """
        result: list[ConcreteResponseSchema | None] = []

        for data in data_list:
            try:
                response: ConcreteResponseSchema | None = await self.add(
                    data=data
                )
                result.append(response)
            except Exception:
                logger.exception(
                    "Ошибка при добавлении объекта в add_many: %s",
                    data,
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
            return await self.helper._process_and_transfer(
                "update", self.response_schema, key=key, value=value, data=data
            )

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
                "first_or_last", self.response_schema,
                limit=limit, by=by, order=order,
            )

    async def delete(self, key: str, value: int) -> None:
        """Удаляет объект и инвалидирует кэш.

        Args:
            key: Название поля.
            value: Значение поля.
        """
        async with self._service_error_boundary():
            await self.repo.delete(key=key, value=value)  # type: ignore
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )

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
            versions = await self.repo.get_all_versions(  # type: ignore[attr-defined]
                object_id=object_id, order=order
            )

            result: list[BaseSchema | None] = []
            for version in versions:
                try:
                    response = await self.helper._transfer(
                        version, self.version_schema
                    )
                    result.append(response)
                except Exception:
                    logger.exception(
                        "Ошибка преобразования версии object_id=%s",
                        object_id,
                    )

            return result

    @response_cache
    async def get_latest_object_version(
        self, object_id: int
    ) -> BaseSchema | None:
        """Получает последнюю версию объекта.

        Args:
            object_id: ID объекта.

        Returns:
            Последняя версия или ``None``.
        """
        async with self._service_error_boundary():
            version = await self.repo.get_latest_version(  # type: ignore
                object_id=object_id
            )
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
            restored_object = await self.repo.restore_to_version(  # type: ignore
                object_id=object_id, transaction_id=transaction_id
            )
            return await self.helper._transfer(
                restored_object, self.response_schema
            )

    async def get_object_changes(
        self, object_id: int
    ) -> list[dict[str, Any]]:
        """Получает список изменений атрибутов объекта.

        Args:
            object_id: ID объекта.

        Returns:
            Список изменений между версиями.
        """
        async with self._service_error_boundary():
            versions = await self.get_all_object_versions(
                object_id=object_id
            )
            if not versions:
                return []

            versions_dict = [
                (
                    version.model_dump()
                    if isinstance(version, BaseSchema)
                    else version
                )
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
                            "transaction_id": current_version.get(
                                "transaction_id"
                            ),
                            "operation_type": current_version.get(
                                "operation_type"
                            ),
                            "changes": diff,
                        }
                    )

            return changes


async def get_service_for_model(model: type[BaseModel]) -> Any:
    """Возвращает сервис для указанной модели.

    Args:
        model: Класс модели.

    Returns:
        Класс сервиса.

    Raises:
        ValueError: Если сервис для модели не найден.
    """
    from importlib import import_module

    service_name = f"{model.__name__}Service"

    try:
        service_module = import_module(
            f"app.services.{model.__tablename__}"
        )
        return getattr(service_module, service_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"Сервис для модели {model.__name__} не найден: {exc}"
        ) from exc


def create_service_class(
    request_schema: type[BaseSchema],
    response_schema: type[BaseSchema],
    version_schema: type[BaseSchema],
    repo: type[SQLAlchemyRepository],
) -> BaseService:  # type: ignore[type-arg]
    """Фабрика для создания экземпляра BaseService."""
    return BaseService(repo, response_schema, request_schema, version_schema)
