from datetime import datetime
from pydantic import Field

from gd_advanced_tools.src.core.schemas import PublicModel


class OrderKindRequestSchema(PublicModel):

    name: str = Field(description="OpenAPI description")
    description: str = Field(description="OpenAPI description")
    skb_uuid: str = Field(description="OpenAPI description")


class OrderKindResponseSchema(OrderKindRequestSchema):

    id: int = Field(description="OpenAPI description")
    created_at: datetime = Field(description="OpenAPI description")
    updated_at: datetime = Field(description="OpenAPI description")
