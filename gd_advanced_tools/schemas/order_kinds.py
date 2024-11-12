from datetime import datetime
from typing import Optional

from gd_advanced_tools.schemas.base import PublicModel


__all__ = ('OrderKindSchemaIn', 'OrderKindSchemaOut', )


class OrderKindSchemaIn(PublicModel):

    name: str = None
    description: Optional[str] = None
    skb_uuid: str = None


class OrderKindSchemaOut(OrderKindSchemaIn):

    id: int
    created_at: datetime
    updated_at: datetime
