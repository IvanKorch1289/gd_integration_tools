import importlib
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union

from fastapi_filter.contrib.sqlalchemy import Filter

from backend.base.models import BaseModel
from backend.base.repository import AbstractRepository
from backend.base.schemas import PublicSchema
from backend.core.redis import caching_decorator


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

    repo: Type[ConcreteRepo] = None
    response_schema: Type[ConcreteResponseSchema] = None
    request_schema: Type[ConcreteRequestSchema] = None

    async def _transfer(
        self,
        instance: BaseModel,
        response_schema: Type[PublicSchema],
    ) -> Union[PublicSchema, None]:
        """
        Преобразует объект модели в схему ответа.

        :param instance: Объект модели.
        :param response_schema: Схема ответа, в которую нужно преобразовать объект.
        :return: Схема ответа или None, если объект не передан.
        """
        if instance and isinstance(instance, self.repo.model):
            return await instance.transfer_model_to_schema(schema=response_schema)
        return instance

    async def _get_and_transfer(
        self, key: str, value: int, response_schema: Type[PublicSchema]
    ) -> Optional[ConcreteResponseSchema]:
        """
        Получает объект по ключу и значению и преобразует его в схему ответа.

        :param key: Название поля.
        :param value: Значение поля.
        :return: Схема ответа или None, если объект не найден.
        """
        instance = await self.repo.get(key=key, value=value)
        return await self._transfer(instance, self.response_schema)

    async def add(self, data: dict) -> Optional[ConcreteResponseSchema]:
        """
        Добавляет новый объект в репозиторий и возвращает его в виде схемы.

        :param data: Данные для создания объекта.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
            instance = await self.repo.add(data=data)
            return await self._transfer(instance, self.response_schema)
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def add_many(
        self, data_list: list[dict]
    ) -> Optional[List[ConcreteResponseSchema]]:
        """
        Добавляет несколько объектов в репозиторий и возвращает их в виде списка схем.

        :param data_list: Список данных для создания объектов.
        :return: Список схем ответа или None, если произошла ошибка.
        """
        try:
            list_instances = [
                await self._transfer(instance, self.response_schema)
                for instance in await self.repo.add_many(data_list=data_list)
            ]
            return list_instances
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def update(
        self, key: str, value: int, data: dict
    ) -> Optional[ConcreteResponseSchema]:
        """
        Обновляет объект в репозитории и возвращает его в виде схемы.

        :param key: Название поля.
        :param value: Значение поля.
        :param data: Данные для обновления объекта.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
            instance = await self.repo.update(key=key, value=value, data=data)
            return await self._transfer(instance, self.response_schema)
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def all(self) -> Optional[List[ConcreteResponseSchema]]:
        """
        Получает все объекты из репозитория и возвращает их в виде списка схем.

        :return: Список схем ответа или None, если произошла ошибка.
        """
        try:
            list_instances = [
                await self._transfer(instance, self.response_schema)
                for instance in await self.repo.all()
            ]
            return list_instances
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def get(self, key: str, value: int) -> Optional[ConcreteResponseSchema]:
        """
        Получает объект по ключу и значению и возвращает его в виде схемы.

        :param key: Название поля.
        :param value: Значение поля.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
            return await self._get_and_transfer(
                key=key, value=value, response_schema=self.response_schema
            )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

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
            list_instances = [
                await self._transfer(instance, self.response_schema)
                for instance in await self.repo.get_by_params(filter=filter)
            ]
            return list_instances
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def get_or_add(
        self, key: str = None, value: int = None, data: dict = None
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
                instance = await self._get_and_transfer(
                    key=key, value=value, response_schema=self.response_schema
                )
            if not instance and data:
                instance = await self.repo.add(data=data)
                return await self._transfer(instance, self.response_schema)
            return instance
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

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
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def get_all_object_versions(self, object_id: int) -> List[Dict[str, Any]]:
        """
        Получает все версии объекта по его id.

        :param object_id: ID объекта.
        :return: Список всех версий объекта в виде схем.
        """
        return await self.repo.get_all_versions(object_id=object_id)

    @caching_decorator
    async def get_latest_object_version(self, object_id: int) -> Dict[str, Any]:
        """
        Получает последнюю версию объекта.

        :param object_id: ID объекта.
        :return: Последняя версия объекта в виде схемы или None, если объект не найден.
        """
        return await self.repo.get_latest_version(object_id=object_id)

    async def restore_object_to_version(
        self, object_id: int, transaction_id: int
    ) -> Dict[str, Any]:
        """
        Восстанавливает объект до указанной версии.

        :param object_id: ID объекта.
        :param transaction_id: ID транзакции, до которой нужно восстановить объект.
        :return: Восстановленный объект в виде схемы или None, если произошла ошибка.
        """
        restored_object = await self.repo.restore_to_version(
            object_id=object_id, transaction_id=transaction_id
        )
        return await restored_object

    @caching_decorator
    async def get_object_changes(self, object_id: int) -> List[Dict[str, Any]]:
        """
        Получает список изменений атрибутов объекта.

        :param object_id: ID объекта.
        :return: Список изменений атрибутов объекта.
        """
        return await self.repo.get_changes(object_id=object_id)


async def get_service_for_model(model: Type[BaseModel]) -> Type[BaseService]:
    """
    Возвращает сервис для указанной модели.

    Аргументы:
        model (Type[BaseModel]): Класс модели.

    Возвращает:
        Type[BaseService]: Класс сервиса, связанного с моделью.

    Исключения:
        ValueError: Если сервис для модели не найден.
    """
    # Формируем имя сервиса
    service_name = f"{model.__name__}Service"
    # Импортируем модуль сервисов
    try:
        service_module = importlib.import_module(
            f"backend.{model.__tablename__}.service"
        )
    except ImportError:
        raise ValueError(f"Модуль сервисов для модели {model.__tablename__} не найден.")

    # Получаем класс сервиса
    try:
        service_class = getattr(service_module, service_name)
    except AttributeError:
        raise ValueError(
            f"Сервис {service_name} для модели {model.__tablename__} не найден."
        )

    return service_class
