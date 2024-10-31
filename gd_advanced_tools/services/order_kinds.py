from typing import List, Union

from gd_advanced_tools.models.order_kinds import OrderKind
from gd_advanced_tools.repository.base import AbstractRepository
from gd_advanced_tools.schemas.order_kinds import OrderKindRequestSchema, OrderKindResponseSchema


class OrdersKindService:

    def __init__(self, order_kinds_repo: AbstractRepository):
        self.order_kinds_repo = order_kinds_repo()
        self.response_schema = OrderKindResponseSchema

    async def add(self, schema: OrderKindRequestSchema) -> OrderKindResponseSchema:
        try:
            instance: OrderKind = await self.order_kinds_repo.add(data=schema.model_dump())
            return await instance.transfer_model_to_schema(schema=self.response_schema)
        except Exception as ex:
            return ex

    async def update(self, key: str, value: int, schema: OrderKindRequestSchema) -> OrderKindResponseSchema:
        try:
            instance: OrderKind = await self.order_kinds_repo.update(key=key, value=value, data=schema.model_dump(exclude_unset=True))
            return await instance.transfer_model_to_schema(schema=self.response_schema)
        except Exception as ex:
            return ex

    async def all(self) -> Union[List[OrderKindResponseSchema], None]:
        try:
            list_instances = [
                await instance.transfer_model_to_schema(schema=self.response_schema)
                async for instance in self.order_kinds_repo.all()
            ]
            return list_instances
        except Exception as ex:
            return ex

    async def get(self, key: str, value: int) -> OrderKindResponseSchema:
        instance: OrderKind = await self.order_kinds_repo.get(key=key, value=value)
        return await instance.transfer_model_to_schema(schema=self.response_schema)

    async def delete(self, key: str, value: int) -> OrderKindResponseSchema:
        result = await self.order_kinds_repo.delete(key=key, value=value)
        return f'Object (id = {result}) successfully deleted'
