from datetime import datetime

from pydantic import BaseModel, field_validator


class OrderKindIdSchema(BaseModel):
    id: int

    @field_validator('id')
    @classmethod
    async def check_valid_id(cls, id: int) -> int:
        if id < 0:
            raise ValueError('ID должен быть больше 0.')
        return id


class OrderKindAddSchema(BaseModel):
    name: str = None
    description: str = None
    skb_uuid: str = None


class OrderKindGetSchema(OrderKindIdSchema, OrderKindAddSchema):
    created_at: datetime = None
    updated_at: datetime = None
