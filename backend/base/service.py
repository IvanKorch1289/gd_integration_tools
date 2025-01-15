import sys
import traceback
from typing import Generic, List, Optional, Type, TypeVar

from fastapi_filter.contrib.sqlalchemy import Filter

from backend.base.repository import AbstractRepository
from backend.base.schemas import PublicSchema
from backend.core.redis import caching_decorator


ConcreteRepo = TypeVar("ConcreteRepo", bound=AbstractRepository)
ConcreteResponseSchema = TypeVar("ConcreteResponseSchema", bound=PublicSchema)


class BaseService(Generic[ConcreteRepo]):
    """
    Базовый сервис для работы с репозиториями и преобразования данных в схемы.

    Атрибуты:
        repo (Type[ConcreteRepo]): Репозиторий, связанный с сервисом.
        response_schema (Type[ConcreteResponseSchema]): Схема для преобразования данных.
    """

    repo: Type[ConcreteRepo] = None
    response_schema: Type[ConcreteResponseSchema] = None

    async def _transfer(self, instance) -> Optional[ConcreteResponseSchema]:
        """
        Преобразует объект модели в схему ответа.

        :param instance: Объект модели.
        :return: Схема ответа или None, если объект не передан.
        """
        if instance and isinstance(instance, self.repo.model):
            return await instance.transfer_model_to_schema(schema=self.response_schema)
        return instance

    async def _get_and_transfer(
        self, key: str, value: int
    ) -> Optional[ConcreteResponseSchema]:
        """
        Получает объект по ключу и значению и преобразует его в схему ответа.

        :param key: Название поля.
        :param value: Значение поля.
        :return: Схема ответа или None, если объект не найден.
        """
        instance = await self.repo.get(key=key, value=value)
        return await self._transfer(instance)

    async def add(self, data: dict) -> Optional[ConcreteResponseSchema]:
        """
        Добавляет новый объект в репозиторий и возвращает его в виде схемы.

        :param data: Данные для создания объекта.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
            instance = await self.repo.add(data=data)
            return await self._transfer(instance)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return None

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
                await self._transfer(instance)
                for instance in await self.repo.add_many(data_list=data_list)
            ]
            return list_instances
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return None

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
            return await self._transfer(instance)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return None

    @caching_decorator
    async def all(self) -> Optional[List[ConcreteResponseSchema]]:
        """
        Получает все объекты из репозитория и возвращает их в виде списка схем.

        :return: Список схем ответа или None, если произошла ошибка.
        """
        try:
            list_instances = [
                await self._transfer(instance) for instance in await self.repo.all()
            ]
            return list_instances
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @caching_decorator
    async def get(self, key: str, value: int) -> Optional[ConcreteResponseSchema]:
        """
        Получает объект по ключу и значению и возвращает его в виде схемы.

        :param key: Название поля.
        :param value: Значение поля.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
            return await self._get_and_transfer(key=key, value=value)
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

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
                await self._transfer(instance)
                for instance in await self.repo.get_by_params(filter=filter)
            ]
            return list_instances
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def get_or_add(
        self, key: str, value: int, data: dict = None
    ) -> Optional[ConcreteResponseSchema]:
        """
        Получает объект по ключу и значению. Если объект не найден, добавляет его.

        :param key: Название поля.
        :param value: Значение поля.
        :param data: Данные для создания объекта, если он не найден.
        :return: Схема ответа или None, если произошла ошибка.
        """
        try:
            instance = await self._get_and_transfer(key=key, value=value)
            if not instance and data:
                instance = await self.repo.add(data=data)
                return await self._transfer(instance)
            return instance
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

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
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return str(ex)
