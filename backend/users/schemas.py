from datetime import datetime

from pydantic import EmailStr, Field, SecretStr

from backend.base.schemas import PublicSchema


__all__ = (
    "UserSchemaIn",
    "UserSchemaOut",
    "UserVersionSchemaOut",
)


class UserSchemaIn(PublicSchema):
    """
    Схема для ввода данных пользователя.

    Атрибуты:
        username (str): Имя пользователя (длина от 3 до 50 символов).
        password (SecretStr): Пароль пользователя (длина от 8 символов).
    """

    username: str = Field(
        ..., min_length=3, max_length=50, description="Имя пользователя"
    )
    password: SecretStr = Field(
        ...,
        min_length=8,
        format="password",
        description="Пароль пользователя",
    )


class UserSchemaOut(PublicSchema):
    """
    Схема для вывода данных пользователя.

    Атрибуты:
        id (int): Идентификатор пользователя.
        username (str): Имя пользователя (длина от 3 до 50 символов).
        email (EmailStr | None): Электронная почта пользователя.
        created_at (datetime): Дата создания пользователя.
        updated_at (datetime | None): Дата последнего обновления пользователя.
        is_superuser (bool): Является ли пользователь суперпользователем.
        is_active (bool): Активен ли пользователь.
    """

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

    class Config:
        """Конфигурация схемы."""

        exclude = {"password"}  # Исключаем поле `password`


class UserVersionSchemaOut(UserSchemaOut):
    """
    Схема для вывода данных о версии пользователя.

    Наследует все атрибуты `UserSchemaOut` и добавляет:
        operation_type (int): Тип операции (например, создание, обновление).
        transaction_id (int): Идентификатор транзакции.
    """

    operation_type: int = Field(..., description="Тип операции")
    transaction_id: int = Field(..., description="Идентификатор транзакции")
