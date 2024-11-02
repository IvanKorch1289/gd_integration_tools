from datetime import datetime
from typing import Optional

from gd_advanced_tools.schemas.base import PublicModel


class OrderKindSchemaIn(PublicModel):

    name: str
    description: Optional[str] = None
    skb_uuid: str


class OrderKindSchemaOut(OrderKindSchemaIn):

    id: int
    created_at: datetime
    updated_at: datetime
