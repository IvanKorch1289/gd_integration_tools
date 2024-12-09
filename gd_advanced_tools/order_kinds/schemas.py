from datetime import datetime

from gd_advanced_tools.base.schemas import PublicSchema


__all__ = (
    "OrderKindSchemaIn",
    "OrderKindSchemaOut",
)


class OrderKindSchemaIn(PublicSchema):

    name: str = None
    description: str | None = None
    skb_uuid: str = None


class OrderKindSchemaOut(OrderKindSchemaIn):

    id: int
    created_at: datetime
    updated_at: datetime
