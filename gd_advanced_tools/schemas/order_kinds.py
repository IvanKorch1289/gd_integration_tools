from datetime import datetime

from gd_advanced_tools.schemas.base import PublicModel

__all__ = (
    "OrderKindSchemaIn",
    "OrderKindSchemaOut",
)


class OrderKindSchemaIn(PublicModel):

    name: str = None
    description: str | None = None
    skb_uuid: str = None


class OrderKindSchemaOut(OrderKindSchemaIn):

    id: int
    created_at: datetime
    updated_at: datetime
