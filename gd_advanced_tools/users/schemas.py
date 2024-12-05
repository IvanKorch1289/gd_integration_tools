from datetime import datetime

from pydantic import EmailStr, Field, SecretStr

from gd_advanced_tools.base.schemas import PublicModel


__all__ = (
    "UserSchemaIn",
    "UserSchemaOut",
)


class UserSchemaIn(PublicModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: SecretStr = Field(..., min_length=8)


class UserSchemaOut(UserSchemaIn):
    id: int
    created_at: datetime
    updated_at: datetime | None
    is_superuser: bool
    is_active: bool
