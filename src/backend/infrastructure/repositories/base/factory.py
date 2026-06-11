from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Params
from sqlalchemy import (
    Insert,
    Result,
    Select,
    Update,
    asc,
    delete,
    desc,
    func,
    inspect,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_continuum import version_class

from src.backend.core.errors import DatabaseError, NotFoundError
from src.backend.infrastructure.database.models.base import BaseModel
from src.backend.infrastructure.database.session_manager import main_session_manager





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
