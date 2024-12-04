from pydantic import BaseModel, EmailStr

from gd_advanced_tools.schemas.base import PublicModel


__all__ = (
    "UserSchemaIn",
    "UserSchemaOut",
)


class UserSchemaIn(PublicModel):
    email: EmailStr
    password: str


class UserSchemaOut(BaseModel):
    id: int
    email: EmailStr
    is_active: bool
    is_superuser: bool
