from typing import List, Optional

from gd_advanced_tools.models.order_kinds import OrderKind
from gd_advanced_tools.repository.base import AbstractRepository
from gd_advanced_tools.schemas.base import ResponseMulti
from gd_advanced_tools.schemas.order_kinds import (
    OrderKindSchemaIn,
    OrderKindSchemaOut
)


class OrdersKindService:

    def __init__(self, order_kinds_repo: AbstractRepository):
        self.order_kinds_repo = order_kinds_repo()
        self.response_schema = OrderKindSchemaOut

    async def add(
        self,
        schema: OrderKindSchemaIn
    ) -> Optional[OrderKindSchemaOut]:
        try:
            instance: OrderKind = await self.order_kinds_repo.add(
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
        schema: OrderKindSchemaIn
    ) -> Optional[OrderKindSchemaOut]:
        try:
            instance: OrderKind = await self.order_kinds_repo.update(
                key=key,
                value=value,
                data=schema.model_dump(exclude_unset=True)
            )
            return await (
                instance.transfer_model_to_schema(schema=self.response_schema)
                if instance else None
            )
        except Exception as ex:
            return ex

    async def all(self) -> Optional[List[ResponseMulti]]:
        try:
            list_instances = [
                await instance.transfer_model_to_schema(
                    schema=self.response_schema
                )
                async for instance in self.order_kinds_repo.all()
            ]
            return list_instances
        except Exception as ex:
            return ex

    async def get(
        self,
        key: str,
        value: int
    ) -> Optional[OrderKindSchemaOut]:
        instance: OrderKind = await self.order_kinds_repo.get(
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
        schema: OrderKindSchemaIn = None
    ) -> Optional[OrderKindSchemaOut]:
        instance: OrderKind = await self.order_kinds_repo.get(
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
    ) -> Optional[OrderKindSchemaOut]:
        result = await self.order_kinds_repo.delete(key=key, value=value)
        return f'Object (id = {result}) successfully deleted'
