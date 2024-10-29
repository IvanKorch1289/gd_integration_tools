from gd_advanced_tools.src.core.repository import BaseRepository

from gd_advanced_tools.src.kinds.models import OrderKind
from gd_advanced_tools.src.kinds.schemas import OrderKindPublic


class OrdersKindRepository(BaseRepository[OrderKind]):
    schema_class = OrderKind

    async def add(self, schema: OrderKindPublic) -> OrderKindPublic:
        instance: OrderKind = await self._save(schema.model_dump())
        return OrderKindPublic.model_validate(instance)
