from __future__ import annotations

from src.backend.core.domain.models.base import BaseModel
from src.backend.infrastructure.repositories.base.sqlalchemy import SQLAlchemyRepository


async def get_repository_for_model(
    model: type[BaseModel],
) -> type[SQLAlchemyRepository]:
    """
    Возвращает класс репозитория для указанной модели.

    """
    from importlib import import_module

    repository_name = f"{model.__name__}Repository"  # Формируем имя репозитория

    try:
        # Импортируем модуль репозитория для указанной модели
        repository_module = import_module(
            f"src.backend.infrastructure.repositories.{model.__tablename__}"
        )
        return getattr(repository_module, repository_name)  # Получаем класс репозитория
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"Репозиторий для модели {model.__name__} не найден: {exc!s}")
