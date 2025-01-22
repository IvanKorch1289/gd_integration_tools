import importlib
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union

from fastapi_filter.contrib.sqlalchemy import Filter

from backend.base.models import BaseModel
from backend.base.repository import AbstractRepository
from backend.base.schemas import PublicSchema
from backend.core.redis import caching_decorator
from backend.core.utils import utilities


# Определение типов для Generic
ConcreteRepo = TypeVar("ConcreteRepo", bound=AbstractRepository)
ConcreteResponseSchema = TypeVar("ConcreteResponseSchema", bound=PublicSchema)
ConcreteRequestSchema = TypeVar("ConcreteRequestSchema", bound=PublicSchema)


class BaseService(Generic[ConcreteRepo]):
    """
    Базовый сервис для работы с репозиториями и преобразования данных в схемы.

    Атрибуты:
        repo (Type[ConcreteRepo]): Репозиторий, связанный с сервисом.
        response_schema (Type[ConcreteResponseSchema]): Схема для преобразования данных.
        request_schema (Type[ConcreteRequestSchema]): Схема для валидации входных данных.
    """

    def __init__(
        self,
        repo: Type[ConcreteRepo] = None,
        response_schema: Type[ConcreteResponseSchema] = None,
        request_schema: Type[ConcreteRequestSchema] = None,
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

    async def _transfer(
        self,
        instance: Any,
        response_schema: Type[PublicSchema],
        is_versioned: bool = False,
    ) -> Union[PublicSchema, None]:
        """
        Преобразует объект модели в схему ответа.

        :param instance: Объект модели.
        :param response_schema: Схема ответа, в которую нужно преобразовать объект.
        :param is_versioned: Флаг, указывающий, что объект является версией.
        :return: Схема ответа или None, если объект не передан.
        """
        if instance:
            # Преобразуем объект модели в словарь, если утилита требует словарь
            instance_dict = {
                c.name: getattr(instance, c.name) for c in instance.__table__.columns
            }
            return await utilities.transfer_model_to_schema(
                instance=instance_dict,  # Передаем словарь вместо объекта модели
                schema=response_schema,
                is_versioned=is_versioned,
            )
        return instance

    async def _transfer_versioned(
        self, instance: Any, response_schema: Type[PublicSchema]
    ) -> Union[PublicSchema, None]:
        """
        Преобразует версионный объект модели в схему ответа.

        :param instance: Объект модели.
        :param response_schema: Схема ответа, в которую нужно преобразовать объект.
        :return: Схема ответа или None, если объект не передан.
        """
        return await self._transfer(instance, response_schema, is_versioned=True)

    async def _process_and_transfer(
        self,
        repo_method: str,
        response_schema: Type[PublicSchema],
        *args,
        **kwargs,
    ) -> Any:
        """
        Выполняет метод репозитория и преобразует результат в схему.

        :param repo_method: Название метода репозитория.
        :param response_schema: Схема ответа.
        :param args: Аргументы для метода репозитория.
        :param kwargs: Ключевые аргументы для метода репозитория.
        :return: Результат в виде схемы или None, если произошла ошибка.
        """
        try:
            instance = await getattr(self.repo, repo_method)(*args, **kwargs)
            return await self._transfer(instance, response_schema)
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def add(self, data: Dict[str, Any]) -> Optional[ConcreteResponseSchema]:
        """
        Добавляет новый объект в репозиторий и возвращает его в виде схемы.

        :param data: Данные для создания объекта.
        :return: Схема ответа или None, если произошла ошибка.
        """
        return await self._process_and_transfer("add", self.response_schema, data=data)

    async def add_many(
        self, data_list: List[Dict[str, Any]]
    ) -> Optional[List[ConcreteResponseSchema]]:
        """
        Добавляет несколько объектов в репозиторий и возвращает их в виде списка схем.

        :param data_list: Список данных для создания объектов.
        :return: Список схем ответа или None, если произошла ошибка.
        """
        try:
            instances = await self.repo.add_many(data_list=data_list)
            return [
                await self._transfer(instance, self.response_schema)
                for instance in instances
            ]
        except Exception:
            raise

    async def update(
        self, key: str, value: int, data: Dict[str, Any]
    ) -> Optional[ConcreteResponseSchema]:
        """
        Обновляет объект в репозитории и возвращает его в виде схемы.

        :param key: Название поля.
        :param value: Значение поля.
        :param data: Данные для обновления объекта.
        :return: Схема ответа или None, если произошла ошибка.
        """
        return await self._process_and_transfer(
            "update", self.response_schema, key=key, value=value, data=data
        )

    @caching_decorator
    async def all(self) -> Optional[List[ConcreteResponseSchema]]:
        """
        Получает все объекты из репозитория и возвращает их в виде списка схем.

        :return: Список схем ответа или None, если произошла ошибка.
        """
        try:
            instances = await self.repo.all()
            return [
                await self._transfer(instance, self.response_schema)
                for instance in instances
            ]
        except Exception:
            raise

    @caching_decorator
    async def get(self, key: str, value: int) -> Optional[ConcreteResponseSchema]:
        """
        Получает объект по ключу и значению и возвращает его в виде схемы.

        :param key: Название поля.
        :param value: Значение поля.
        :return: Схема ответа или None, если произошла ошибка.
        """
        return await self._process_and_transfer(
            "get", self.response_schema, key=key, value=value
        )

    @caching_decorator
    async def get_by_params(
        self, filter: Filter
    ) -> Optional[List[ConcreteResponseSchema]]:
        """
        Получает объекты по параметрам фильтра и возвращает их в виде списка схем.

        :param filter: Фильтр для поиска объектов.
        :return: Список схем ответа или None, если произошла ошибка.
        """
        try:
            instances = await self.repo.get_by_params(filter=filter)
            return [
                await self._transfer(instance, self.response_schema)
                for instance in instances
            ]
        except Exception:
            raise

    async def get_or_add(
        self, key: str = None, value: int = None, data: Dict[str, Any] = None
    ) -> Optional[ConcreteResponseSchema]:
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
                instance = await self._process_and_transfer(
                    "get", self.response_schema, key=key, value=value
                )
            if not instance and data:
                instance = await self._process_and_transfer(
                    "add", self.response_schema, data=data
                )
            return instance
        except Exception:
            raise

    async def delete(self, key: str, value: int) -> str:
        """
        Удаляет объект по ключу и значению.

        :param key: Название поля.
        :param value: Значение поля.
        :return: Сообщение об успешном удалении или информация об ошибке.
        """
        try:
            await self.repo.delete(key=key, value=value)
            return f"Object (id = {value}) successfully deleted"
        except Exception:
            raise

    async def get_all_object_versions(
        self, object_id: int
    ) -> Optional[List[PublicSchema]]:
        """
        Получает все версии объекта по его id.

        :param object_id: ID объекта.
        :return: Список всех версий объекта в виде схем.
        """
        from backend.orderkinds.schemas import OrderKindVersionSchemaOut

        versions = await self.repo.get_all_versions(object_id=object_id)
        return [
            await self._transfer_versioned(version, OrderKindVersionSchemaOut)
            for version in versions
        ]

    @caching_decorator
    async def get_latest_object_version(self, object_id: int) -> Optional[PublicSchema]:
        """
        Получает последнюю версию объекта.

        :param object_id: ID объекта.
        :return: Последняя версия объекта в виде схемы или None, если объект не найден.
        """
        from backend.orderkinds.schemas import OrderKindVersionSchemaOut

        version = await self.repo.get_latest_version(object_id=object_id)
        return await self._transfer_versioned(version, OrderKindVersionSchemaOut)

    async def restore_object_to_version(
        self, object_id: int, transaction_id: int
    ) -> Optional[PublicSchema]:
        """
        Восстанавливает объект до указанной версии.

        :param object_id: ID объекта.
        :param transaction_id: ID транзакции, до которой нужно восстановить объект.
        :return: Восстановленный объект в виде схемы или None, если произошла ошибка.
        """
        from backend.orderkinds.schemas import OrderKindVersionSchemaOut

        restored_object = await self.repo.restore_to_version(
            object_id=object_id, transaction_id=transaction_id
        )
        return await self._transfer_versioned(
            restored_object, OrderKindVersionSchemaOut
        )

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

            versions_dict = [version.model_dump() for version in versions]
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
            raise Exception(f"Ошибка при получении изменений: {exc}") from exc


async def get_service_for_model(model: Type[BaseModel]) -> Type[BaseService]:
    """
    Возвращает сервис для указанной модели.

    :param model: Класс модели.
    :return: Класс сервиса, связанного с моделью.
    :raises ValueError: Если сервис для модели не найден.
    """
    service_name = f"{model.__name__}Service"
    try:
        service_module = importlib.import_module(
            f"backend.{model.__tablename__}.service"
        )
        service_class = getattr(service_module, service_name)
        return service_class
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"Сервис для модели {model.__name__} не найден: {str(exc)}")
