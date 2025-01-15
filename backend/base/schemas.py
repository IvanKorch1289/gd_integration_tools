import json
from typing import Any, Dict

from pydantic import BaseModel, EmailStr


def to_camelcase(string: str) -> str:
    """
    Преобразует строку из snake_case в camelCase.

    :param string: Строка в формате snake_case.
    :return: Строка в формате camelCase.
    """
    return "".join(
        word.capitalize() if index else word
        for index, word in enumerate(string.split("_"))
    )


class EmailSchema(BaseModel):
    """
    Схема для представления данных электронной почты.

    Атрибуты:
        to_email (EmailStr): Адрес электронной почты получателя.
        subject (str): Тема письма.
        message (str): Текст сообщения.
    """

    to_email: EmailStr
    subject: str
    message: str


class PublicSchema(BaseModel):
    """
    Базовая схема для публичных моделей с поддержкой camelCase и дополнительных настроек.

    Конфигурация:
        - extra: Игнорировать дополнительные поля.
        - from_attributes: Разрешить создание объектов из атрибутов.
        - use_enum_values: Использовать значения перечислений.
        - validate_assignment: Проверять присваивание значений.
        - alias_generator: Генератор алиасов для преобразования имен полей.
        - populate_by_name: Разрешить заполнение по имени поля.
        - arbitrary_types_allowed: Разрешить использование произвольных типов.
    """

    class Config:
        extra = "ignore"
        from_attributes = True
        use_enum_values = True
        validate_assignment = True
        alias_generator = to_camelcase
        populate_by_name = True
        arbitrary_types_allowed = True

    def encoded_dict(self, by_alias: bool = True) -> Dict[str, Any]:
        """
        Возвращает словарь с данными модели, закодированными в JSON.

        :param by_alias: Если True, использует алиасы для имен полей.
        :return: Словарь с данными модели.
        """
        return json.loads(self.model_dump_json(by_alias=by_alias))
