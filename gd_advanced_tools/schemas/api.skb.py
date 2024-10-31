from datetime import datetime
from pydantic import Field

from gd_advanced_tools.schemas.base import PublicModel


class OrderKindResponseSchema(PublicModel):

    id: int = Field(description="OpenAPI description")
    created_at: datetime = Field(description="OpenAPI description")
    updated_at: datetime = Field(description="OpenAPI description")