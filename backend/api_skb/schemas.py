from uuid import UUID, uuid4

from pydantic import Field

from backend.base.schemas import PublicSchema


__all__ = ("ApiOrderSchemaIn",)


class ApiOrderSchemaIn(PublicSchema):

    Id: UUID = Field(default=uuid4())
    OrderId: UUID = Field(default=uuid4())
    Number: str
    Priority: int = 80
    RequestType: str
