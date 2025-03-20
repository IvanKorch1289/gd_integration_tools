from typing import Any, Dict, List, Type

from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Page, Params

from app.infra.db.models.base import BaseModel
from app.repositories.base import SQLAlchemyRepository
from app.schemas.base import BaseSchema, PaginatedResult
from app.utils.decorators.caching import response_cache
from app.utils.errors import ServiceError
from app.utils.utils import utilities


__all__ = ("create_service_class", "BaseService", "get_service_for_model")


class BaseService[
    ConcreteRepo,
    ConcreteResponseSchema: BaseSchema,
    ConcreteRequestSchema: BaseSchema,
    ConcreteVersionSchema: BaseSchema,
]:
    """
    Базовый сервис для работы с репозиториями и преобразования данных в схемы.

    Атрибуты:
        repo (Type[ConcreteRepo]): Репозиторий, связанный с сервисом.
        response_schema (Type[ConcreteResponseSchema]): Схема для преобразования данных.
        request_schema (Type[ConcreteRequestSchema]): Схема для валидации входных данных.
        response_schema (Type[ConcreteVersionSchema]): Схема для преобразования данных версий.
    """

    class HelperMethods:
        """
        Вспомогательные методы для работы.
        """

        def __init__(self, repo):
            self.repo = repo

        async def _transfer(
            self,
            instance: Any,
            response_schema: Type[BaseSchema],
            from_attributes: bool = True,
        ) -> BaseSchema | None:
            """
            Преобразует объект модели в схему ответа.

            :param instance: Объект модели.
            :param response_schema: Схема ответа, в которую нужно преобразовать объект.
            :param from_attributes: Флаг для указания преобразования связанных моделей.
            :return: Схема ответа или None, если объект не передан.
            """

            if isinstance(instance, BaseModel) or hasattr(
                instance.__class__, "version_parent"
            ):

                return utilities.transfer_model_to_schema(  # type: ignore
                    instance=instance,
                    schema=response_schema,
                    from_attributes=from_attributes,
                )
            return instance

        async def _transfer_paginated(
            self, items: List[Any], response_schema: Type[BaseSchema]
        ) -> List[BaseSchema | None]:
            return [
                await self._transfer(item, response_schema) for item in items
            ]

        async def _process_and_transfer(
            self,
            repo_method: str,
            response_schema: Type[BaseSchema],
            *args,
            **kwargs,
        ) -> Any:
            try:
                # Получаем результат из репозитория
                instance = await getattr(self.repo, repo_method)(
                    *args, **kwargs
                )

                # Обработка пагинированного ответа
                if isinstance(instance, dict) and "items" in instance:
                    items = await self._transfer_paginated(
                        instance["items"], response_schema
                    )
                    return PaginatedResult(
                        items=items, total=instance["total"]
                    )

                # Оригинальная логика
                if not instance:
                    return []
                elif isinstance(instance, list):
                    return (
                        [
                            await self._transfer(item, response_schema)
                            for item in instance
                        ]
                        if instance
                        else []
                    )

                return await self._transfer(instance, response_schema)

            except Exception as exc:
                raise ServiceError from exc

    def __init__(
        self,
        repo: Type[ConcreteRepo] = None,
        response_schema: Type[ConcreteResponseSchema] = None,
        request_schema: Type[ConcreteRequestSchema] = None,
        version_schema: Type[ConcreteVersionSchema] = None,
    ):
        """
        Инициализация сервиса.

        :param repo: Репозиторий, связанный с сервисом.
        :param response_schema: Схема для преобразования данных.
        :param request_schema: Схема для валидации входных данных.
        """
        self.repo = repo
        self.response_schema = response_schema
        self.request_schema = request_schema
        self.version_schema = version_schema
        self.helper = self.HelperMethods(repo)

    async def add(self, data: Dict[str, Any]) -> ConcreteResponseSchema | None:
        """
        Добавляет новый объект в репозиторий и возвращает его в виде схемы.

        :param data: Данные для создания объекта.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
            result: ConcreteResponseSchema | None = (
                await self.helper._process_and_transfer(
                    "add", self.response_schema, data=data
                )
            )
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )
            return result
        except Exception as exc:
            raise ServiceError from exc

    async def add_many(
        self, data_list: List[Dict[str, Any]]
    ) -> List[ConcreteResponseSchema | None]:
        """
        Добавляет несколько объектов в репозиторий и возвращает их в виде списка схем.

        :param data_list: Список данных для создания объектов.
        :return: Список схем ответа или None, если произошла ошибка.
        """
        result: List[ConcreteResponseSchema | None] = []

        for data in data_list:
            try:
                response: ConcreteResponseSchema | None = await self.add(
                    data=data
                )
                result.append(response)
            except Exception:
                pass

        return result

    async def update(
        self, key: str, value: int, data: Dict[str, Any]
    ) -> ConcreteResponseSchema | None:
        """
        Обновляет объект в репозитории и возвращает его в виде схемы.

        :param key: Название поля.
        :param value: Значение поля.
        :param data: Данные для обновления объекта.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
            result = await self.helper._process_and_transfer(
                "update", self.response_schema, key=key, value=value, data=data
            )
            return result
        except Exception as exc:
            raise ServiceError from exc

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
        | List[ConcreteResponseSchema]
        | Page[ConcreteResponseSchema]
        | None
    ):
        """
        Получает объект по ключу и значению, фильтру или все объекты, если ничего не передано.

        :param key: Название поля (опционально).
        :param value: Значение поля (опционально).
        :param filter: Фильтр для запроса (опционально).
        :return: Схема ответа, список схем или None, если произошла ошибка.
        """
        try:
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
        except Exception as exc:
            raise ServiceError from exc

    async def get_or_add(
        self, key: str = None, value: int = None, data: Dict[str, Any] = None
    ) -> ConcreteResponseSchema | None:
        """
        Получает объект по ключу и значению. Если объект не найден, добавляет его.

        :param key: Название поля.
        :param value: Значение поля.
        :param data: Данные для создания объекта, если он не найден.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
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

        except Exception as exc:
            raise ServiceError from exc

    @response_cache
    async def get_first_or_last_with_limit(
        self, limit: int = 1, by: str = "id", order: str = "asc"
    ) -> ConcreteResponseSchema | List[ConcreteResponseSchema] | None:
        try:
            return await self.helper._process_and_transfer(
                "first_or_last",
                self.response_schema,
                limit=limit,
                by=by,
                order=order,
            )
        except Exception as exc:
            raise ServiceError from exc

    async def delete(self, key: str, value: int) -> str:  # type: ignore
        """
        Удаляет объект по ключу и значению.

        :param key: Название поля.
        :param value: Значение поля.
        :return: Сообщение об успешном удалении или информация об ошибке.
        """
        try:
            await self.repo.delete(key=key, value=value)  # type: ignore
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )
        except Exception as exc:
            raise ServiceError from exc

    @response_cache
    async def get_all_object_versions(
        self, object_id: int
    ) -> List[BaseSchema | None]:
        """
        Получает все версии объекта по его id.

        :param object_id: ID объекта.
        :return: Список всех версий объекта в виде схем.
        """
        try:
            versions = await self.repo.get_all_versions(object_id=object_id)  # type: ignore

            result: List[BaseSchema | None] = []

            for version in versions:
                try:
                    response: BaseSchema | None = await self.helper._transfer(
                        version, self.version_schema
                    )
                    result.append(response)
                except Exception:
                    pass

            return result
        except Exception as exc:
            raise ServiceError from exc

    @response_cache
    async def get_latest_object_version(
        self, object_id: int
    ) -> BaseSchema | None:
        """
        Получает последнюю версию объекта.

        :param object_id: ID объекта.
        :return: Последняя версия объекта в виде схемы или None, если объект не найден.
        """
        try:
            version = await self.repo.get_latest_version(object_id=object_id)  # type: ignore
            return await self.helper._transfer(version, self.version_schema)
        except Exception as exc:
            raise ServiceError from exc

    async def restore_object_to_version(
        self, object_id: int, transaction_id: int
    ) -> BaseSchema | None:
        """
        Восстанавливает объект до указанной версии.

        :param object_id: ID объекта.
        :param transaction_id: ID транзакции, до которой нужно восстановить объект.
        :return: Восстановленный объект в виде схемы или None, если произошла ошибка.
        """
        try:
            restored_object = await self.repo.restore_to_version(  # type: ignore
                object_id=object_id, transaction_id=transaction_id
            )

            return await self.helper._transfer(
                restored_object, self.response_schema
            )
        except Exception as exc:
            raise ServiceError from exc

    async def get_object_changes(self, object_id: int) -> List[Dict[str, Any]]:
        """
        Получает список изменений атрибутов объекта.

        :param object_id: ID объекта.
        :return: Список изменений атрибутов объекта.
        """
        try:
            versions = await self.get_all_object_versions(object_id=object_id)
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

            changes = []
            for i in range(1, len(versions_dict)):
                prev_version = versions_dict[i - 1]
                current_version = versions_dict[i]
                transaction_id = current_version.get("transaction_id")
                operation_type = current_version.get("operation_type")

                excluded_fields = {"transaction_id", "operation_type"}
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
                            "transaction_id": transaction_id,
                            "operation_type": operation_type,
                            "changes": diff,
                        }
                    )

            return changes
        except Exception as exc:
            raise ServiceError from exc


async def get_service_for_model(model: Type[BaseModel]):
    """
    Возвращает сервис для указанной модели.

    :param model: Класс модели.
    :return: Класс сервиса, связанного с моделью.
    :raises ValueError: Если сервис для модели не найден.
    """
    from importlib import import_module

    service_name = f"{model.__name__}Service"

    try:
        service_module = import_module(f"app.services.{model.__tablename__}")
        return getattr(service_module, service_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"Сервис для модели {model.__name__} не найден: {str(exc)}"
        )


def create_service_class(
    request_schema: BaseSchema,
    response_schema: BaseSchema,
    version_schema: BaseSchema,
    repo: SQLAlchemyRepository,
) -> BaseService:
    return BaseService(repo, response_schema, request_schema, version_schema)
