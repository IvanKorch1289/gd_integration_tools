from datetime import datetime

from pydantic import EmailStr, Field, SecretStr

from gd_advanced_tools.base.schemas import PublicModel


__all__ = (
    "UserSchemaIn",
    "UserSchemaOut",
)


class UserSchemaIn(PublicModel):
    username: str = Field(
        ..., min_length=3, max_length=50, description="Имя пользователя"
    )
    email: EmailStr = Field(..., description="Электронная почта пользователя")
    password: SecretStr = Field(..., min_length=8, description="Пароль пользователя")


class UserSchemaOut(UserSchemaIn):
    id: int = Field(..., description="Идентификатор пользователя")
    created_at: datetime = Field(..., description="Дата создания пользователя")
    updated_at: datetime | None = Field(
        None, description="Дата последнего обновления пользователя"
    )
    is_superuser: bool = Field(
        False, description="Является ли пользователь суперпользователем"
    )
    is_active: bool = Field(True, description="Активен ли пользователь")
