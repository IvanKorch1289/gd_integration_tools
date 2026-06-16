from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.services.core.base import BaseService

from src.backend.core.interfaces.db_model import DBModelProtocol
from src.backend.core.interfaces.repositories import RepositoryProtocol
from src.backend.schemas.base import BaseSchema


def _is_orm_model(instance: Any) -> bool:
    cls = instance.__class__
    return hasattr(cls, "__tablename__") and hasattr(cls, "__table__")


def _is_orm_model(instance: Any) -> bool:
    """Структурная проверка ORM-модели без зависимости от infrastructure.

    Проект использует SQLAlchemy DeclarativeBase: у любой модели есть
    атрибут ``__tablename__`` (через ``declared_attr``) и ``__table__``.
    Этого достаточно для duck-typing в сервисах.
    """
    cls = instance.__class__
    return hasattr(cls, "__tablename__") and hasattr(cls, "__table__")


async def get_service_for_model(model: type[DBModelProtocol]) -> Any:
    """Возвращает сервис для указанной ORM-модели.

    Args:
        model: Класс ORM-модели (структурно — :class:`DBModelProtocol`).

    Returns:
        Класс сервиса.

    Raises:
        ValueError: Если сервис для модели не найден.
    """
    from importlib import import_module

    service_name = f"{model.__name__}Service"

    try:
        service_module = import_module(f"src.backend.services.{model.__tablename__}")
        return getattr(service_module, service_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"Сервис для модели {model.__name__} не найден: {exc}"
        ) from exc


def create_service_class(
    request_schema: type[BaseSchema],
    response_schema: type[BaseSchema],
    version_schema: type[BaseSchema],
    repo: type[RepositoryProtocol],
) -> BaseService:
    """Фабрика для создания экземпляра BaseService."""
    from src.backend.services.core.base import BaseService

    return BaseService(repo, response_schema, request_schema, version_schema)
