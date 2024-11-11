import sys
import traceback
from typing import Generic, List, Type, TypeVar

from gd_advanced_tools.repository.base import AbstractRepository
from gd_advanced_tools.schemas.base import PublicModel


ConcreteRepo = TypeVar('ConcreteRepo', bound=AbstractRepository)
ConcreteResponseSchema = TypeVar('ConcreteResponseSchema', bound=PublicModel)


class BaseService(Generic[ConcreteRepo]):

    repo: Type[ConcreteRepo] = None
    response_schema: Type[ConcreteResponseSchema] = None

    async def add(
        self,
        schema: PublicModel
    ) -> PublicModel | None:
        try:
            instance = await self.repo.add(
                data=schema.model_dump()
            )
            return await (
                instance.transfer_model_to_schema(schema=self.response_schema)
                if instance else None
            )
        except Exception as ex:
            return ex

    async def update(
        self,
        key: str,
        value: int,
        schema: PublicModel
    ) -> PublicModel | None:
        try:
            instance = await self.repo.update(
                key=key,
                value=value,
                data=schema.model_dump(exclude_unset=True)
            )
            return await (
                instance.transfer_model_to_schema(schema=self.response_schema)
                if instance else None
            )
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def all(self) -> List[PublicModel] | None:
        try:
            list_instances = [
                await instance.transfer_model_to_schema(
                    schema=self.response_schema
                )
                async for instance in self.repo.all()
            ]
            return list_instances
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def get(
        self,
        key: str,
        value: int
    ) -> PublicModel | None:
        instance = await self.repo.get(
            key=key,
            value=value
        )
        return await (
            instance.transfer_model_to_schema(schema=self.response_schema)
            if instance else None
        )

    async def get_or_add(
        self,
        key: str,
        value: int,
        schema: PublicModel = None
    ) -> PublicModel | None:
        instance = await self.repo.get(
            key=key,
            value=value
        )
        return await (
            instance.transfer_model_to_schema(schema=self.response_schema)
            if instance else self.add(schema=schema)
        )

    async def delete(
        self,
        key: str,
        value: int
    ) -> PublicModel | None:
        result = await self.order_kinds_repo.delete(key=key, value=value)
        return f'Object (id = {result}) successfully deleted'
