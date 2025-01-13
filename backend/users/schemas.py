from datetime import datetime

from pydantic import EmailStr, Field, SecretStr

from backend.base.schemas import PublicSchema


__all__ = (
    "UserSchemaIn",
    "UserSchemaOut",
)


class UserSchemaIn(PublicSchema):
    username: str = Field(
        ..., min_length=3, max_length=50, description="Имя пользователя"
    )
    password: SecretStr = Field(..., min_length=8, description="Пароль пользователя")


class UserSchemaOut(PublicSchema):
    id: int = Field(..., description="Идентификатор пользователя")
    username: str = Field(
        ..., min_length=3, max_length=50, description="Имя пользователя"
    )
    email: EmailStr | None = Field(..., description="Электронная почта пользователя")
    created_at: datetime = Field(..., description="Дата создания пользователя")
    updated_at: datetime | None = Field(
        None, description="Дата последнего обновления пользователя"
    )
    is_superuser: bool = Field(
        False, description="Является ли пользователь суперпользователем"
    )
    is_active: bool = Field(True, description="Активен ли пользователь")
