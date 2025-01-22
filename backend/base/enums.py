from enum import Enum
from typing import Dict

from backend.base.models import BaseModel, mapper_registry


def get_user_models() -> Dict[str, str]:
    """
    Получает все пользовательские модели, которые наследуются от BaseModel.

    Возвращает:
        Dict[str, str]: Словарь, где ключ — имя таблицы, а значение — класс модели.
    """
    user_models = {}

    # Используем mapper_registry для получения всех моделей
    for class_ in mapper_registry.mappers:
        model = class_.class_

        if (
            isinstance(model, type)  # Убедимся, что это класс
            and issubclass(model, BaseModel)  # Наследуется от BaseModel
            and model.__name__ != "BaseModel"  # Исключаем саму BaseModel
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
