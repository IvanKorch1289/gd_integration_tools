from typing import Any

from gd_advanced_tools.models import Order
from gd_advanced_tools.repository.base import SQLAlchemyRepository
from gd_advanced_tools.repository.order_kinds import OrderKindRepository
from gd_advanced_tools.schemas import OrderSchemaOut

__all__ = ("OrderRepository",)


class OrderRepository(SQLAlchemyRepository):
    model = Order
    response_schema = OrderSchemaOut

    async def add(self, data: dict[str, Any]) -> Order:
        kind = await OrderKindRepository().get(
            key="skb_uuid", value=data["order_kind_id"]
        )
        if kind:
            data["order_kind_id"] = kind.id
            return await super().add(data=data)
