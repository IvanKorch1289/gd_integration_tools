import sys
import traceback
from typing import Generic, List, Type, TypeVar

from gd_advanced_tools.base.repository import AbstractRepository
from gd_advanced_tools.base.schemas import PublicSchema
from gd_advanced_tools.core.utils import utilities


ConcreteRepo = TypeVar("ConcreteRepo", bound=AbstractRepository)
ConcreteResponseSchema = TypeVar("ConcreteResponseSchema", bound=PublicSchema)


class BaseService(Generic[ConcreteRepo]):

    repo: Type[ConcreteRepo] = None
    response_schema: Type[ConcreteResponseSchema] = None

    async def add(self, data: dict) -> PublicSchema | None:
        try:
            instance = await self.repo.add(data=data)
            return await (
                instance.transfer_model_to_schema(schema=self.response_schema)
                if instance
                else None
            )
        except Exception as ex:
            return ex

    async def update(self, key: str, value: int, data: dict) -> PublicSchema | None:
        try:
            instance = await self.repo.update(key=key, value=value, data=data)
            return await (
                instance.transfer_model_to_schema(schema=self.response_schema)
                if instance
                else None
            )
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @utilities.caching(schema=response_schema, expire=300)
    async def all(self) -> List[PublicSchema] | None:
        try:
            list_instances = [
                await instance.transfer_model_to_schema(schema=self.response_schema)
                for instance in await self.repo.all()
            ]
            return list_instances
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @utilities.caching(schema=response_schema, expire=300)
    async def get(self, key: str, value: int) -> PublicSchema | None:
        try:
            instance = await self.repo.get(key=key, value=value)
            return await (
                instance.transfer_model_to_schema(schema=self.response_schema)
                if instance
                else None
            )
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @utilities.caching(schema=response_schema, expire=300)
    async def get_by_params(self, filter: dict) -> List[PublicSchema] | None:
        try:
            list_instances = [
                await instance.transfer_model_to_schema(schema=self.response_schema)
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
            instance = await self.repo.get(key=key, value=value)
            return await (
                instance.transfer_model_to_schema(schema=self.response_schema)
                if instance
                else self.repo.add(data=data)
            )
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
