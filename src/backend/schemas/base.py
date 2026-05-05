"""Базовые Pydantic-схемы приложения.

Все публичные схемы наследуются от ``BaseSchema``,
которая обеспечивает camelCase алиасы, from_attributes
и другие общие настройки (Pydantic v2).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr

__all__ = ("EmailSchema", "BaseSchema", "FileResponse", "PaginatedResult")


def to_camelcase(string: str) -> str:
    """Преобразует snake_case в camelCase.

    Args:
        string: Строка в snake_case.

    Returns:
        Строка в camelCase.
    """
    return "".join(
        word.capitalize() if index else word
        for index, word in enumerate(string.split("_"))
    )


class EmailSchema(BaseModel):
    """Схема email-сообщения.

    Attrs:
        to_emails: Список адресов получателей.
        subject: Тема письма.
        message: Текст сообщения.
    """

    to_emails: list[EmailStr]
    subject: str
    message: str


class BaseSchema(BaseModel):
    """Базовая схема для публичных моделей.

    Использует Pydantic v2 ``model_config`` вместо
    deprecated ``class Config``.
    """

    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        use_enum_values=True,
        validate_assignment=True,
        alias_generator=to_camelcase,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    def encoded_dict(self, by_alias: bool = True) -> dict[str, Any]:
        """Сериализует схему в словарь.

        Использует ``model_dump(mode="python")`` напрямую,
        без промежуточной JSON-строки (на 20-40% быстрее).

        Args:
            by_alias: Использовать camelCase алиасы.

        Returns:
            Словарь с данными модели.
        """
        return self.model_dump(by_alias=by_alias, mode="python")


class FileResponse(BaseModel):
    """Схема ответа для файловых операций."""

    filename: str
    key: str
    size: int
    headers: dict[str, Any]
    metadata: dict[str, Any] | None = None


class PaginatedResult(BaseModel):
    """Результат пагинированного запроса."""

    items: list[Any]
    total: int
