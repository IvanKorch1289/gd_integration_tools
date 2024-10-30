from typing import Any, AsyncGenerator
from gd_advanced_tools.src.core.repository import BaseRepository

from gd_advanced_tools.src.kinds.models import OrderKind
from gd_advanced_tools.src.kinds.schemas import OrderKindRequestSchema, OrderKindResponseSchema


class OrdersKindRepository(BaseRepository[OrderKind]):
    schema_class = OrderKind

    async def add(self, schema: OrderKindRequestSchema) -> OrderKindResponseSchema:
        instance: OrderKind = await self._save(payload=schema.model_dump())
        return OrderKindResponseSchema.model_validate(instance)

    async def update(self, key: str, value: int, schema: OrderKindRequestSchema) -> OrderKindResponseSchema:
        instance: OrderKind = await self._update(key=key, value=value, payload=schema.model_dump(exclude_unset=True))
        return OrderKindResponseSchema.model_validate(instance)

    async def all(self) -> AsyncGenerator[OrderKindResponseSchema, None]:
        async for instance in self._all():
            yield OrderKindResponseSchema.model_validate(instance)

    async def get(self, key: str, value: int) -> OrderKindResponseSchema:
        instance: OrderKind = await self._get(key=key, value=value)
        return OrderKindResponseSchema.model_validate(instance)
