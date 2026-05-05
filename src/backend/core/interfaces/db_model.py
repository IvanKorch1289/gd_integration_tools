"""Структурный протокол ORM-модели для использования из services-слоя.

Wave 6.2: добавлено для замены прямого импорта
``src.infrastructure.database.models.base.BaseModel`` в services/core/base.py.

ORM-модель в проекте — это SQLAlchemy ``DeclarativeBase`` с обязательными
атрибутами ``id``, ``__tablename__`` и ``to_dict``. Этого достаточно для
duck-typing проверок в services без зависимости от конкретного слоя БД.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ("DBModelProtocol",)


@runtime_checkable
class DBModelProtocol(Protocol):
    """Минимальный контракт ORM-модели, видимый сервисам.

    Используется для:
    * isinstance-чек в ``BaseService.HelperMethods._transfer``;
    * получения сервиса по типу модели (``get_service_for_model``).
    """

    id: Any

    @property
    def __tablename__(self) -> str:  # pragma: no cover - structural
        ...

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - structural
        ...
