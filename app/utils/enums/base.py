from enum import Enum
from typing import Dict

from app.infra.db.models.base import BaseModel, mapper_registry


__all__ = ("get_user_models", "get_model_enum")


def get_user_models() -> Dict[str, BaseModel]:
    """
    Получает все пользовательские модели, которые наследуются от BaseModel.

    Возвращает:
        Dict[str, BaseModel]: Словарь, где ключ — имя таблицы, а значение — класс модели.
    """
    user_models: dict = {}

    # Используем mapper_registry для получения всех моделей
    for class_ in mapper_registry.mappers:
        model = class_.class_

        if (
            isinstance(model, type)
            and issubclass(model, BaseModel)
            and model.__name__ != "BaseModel"
        ):
            user_models[model.__tablename__] = model

    return user_models


def get_model_enum() -> Enum:
    """
    Создает перечисление (Enum) на основе пользовательских моделей.

    Возвращает:
        Enum: Перечисление, где ключи — имена таблиц, а значения — классы моделей.
    """
    return Enum("ModelEnum", get_user_models())
