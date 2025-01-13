import sys
import traceback
from typing import Generic, List, Type, TypeVar

from fastapi_filter.contrib.sqlalchemy import Filter

from backend.base.repository import AbstractRepository
from backend.base.schemas import PublicSchema
from backend.core.utils import utilities


ConcreteRepo = TypeVar("ConcreteRepo", bound=AbstractRepository)
ConcreteResponseSchema = TypeVar("ConcreteResponseSchema", bound=PublicSchema)


class BaseService(Generic[ConcreteRepo]):

    repo: Type[ConcreteRepo] = None
    response_schema: Type[ConcreteResponseSchema] = None

    async def _transfer(self, instance):
        if instance and isinstance(instance, self.repo.model):
            return await instance.transfer_model_to_schema(schema=self.response_schema)
        return instance

    async def _get_and_transfer(self, key: str, value: int):
        instance = await self.repo.get(key=key, value=value)
        return await self._transfer(instance)

    async def add(self, data: dict) -> PublicSchema | None:
        try:
            instance = await self.repo.add(data=data)
            return await self._transfer(instance)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return None

    async def add_many(self, data_list: list[dict]) -> PublicSchema | None:
        try:
            list_instances = [
                await instance
                for instance in await self.repo.add_many(data_list=data_list)
            ]
            return list_instances
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return None

    async def update(self, key: str, value: int, data: dict) -> PublicSchema | None:
        try:
            instance = await self.repo.update(key=key, value=value, data=data)
            return await self._transfer(instance)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return None

    @utilities.caching(schema=response_schema, expire=300)
    async def all(self) -> List[PublicSchema] | None:
        try:
            list_instances = [
                await self._transfer(instance) for instance in await self.repo.all()
            ]
            return list_instances
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @utilities.caching(schema=response_schema, expire=300)
    async def get(self, key: str, value: int) -> PublicSchema | None:
        try:
            return await self._get_and_transfer(key=key, value=value)
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @utilities.caching(schema=response_schema, expire=300)
    async def get_by_params(self, filter: Filter) -> List[PublicSchema] | None:
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
    ) -> PublicSchema | None:
        try:
            instance = await self._get_and_transfer(key=key, value=value)
            if not instance:
                await self.repo.add(data=data)
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def delete(self, key: str, value: int) -> str:
        try:
            await self.repo.delete(key=key, value=value)
            return f"Object (id = {value}) successfully deleted"
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex
