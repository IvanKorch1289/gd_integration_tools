from pydantic import Field

from gd_advanced_tools.src.core.schemas import PublicModel


class _OrderKindPublic(PublicModel):

    name: str = Field(description="OpenAPI description")
    description: str = Field(description="OpenAPI description")
    skb_uuid: str = Field(description="OpenAPI description")


class OrderKindCreateRequestBody(_OrderKindPublic):

    pass


class OrderKindPublic(_OrderKindPublic):

    id: int
