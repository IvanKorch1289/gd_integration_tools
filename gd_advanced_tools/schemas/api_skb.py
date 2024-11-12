from uuid import UUID, uuid4

from pydantic import Field
from gd_advanced_tools.schemas.base import PublicModel


__all__ = ('ApiOrderSchemaIn', )


class ApiOrderSchemaIn(PublicModel):

    Id: UUID = Field(default=uuid4())
    OrderId: UUID = Field(default=uuid4())
    Number: str
    Priority: int = 80
    RequestType: str
