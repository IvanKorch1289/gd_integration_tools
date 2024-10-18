from datetime import datetime

from pydantic import BaseModel


class OrderKindIdSchema(BaseModel):
    id: int


class OrderKindAddSchema(BaseModel):
    name: str = None
    description: str = None
    skb_uuid: str = None


class OrderKindGetSchema(OrderKindIdSchema, OrderKindAddSchema):
    created_at: datetime = None
    updated_at: datetime = None
