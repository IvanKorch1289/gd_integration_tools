from datetime import datetime
from typing import Annotated, Any, Dict

from pydantic import SecretStr
from sqlalchemy import Integer, MetaData, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, registry
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.plugins import (
    ActivityPlugin,
    PropertyModTrackerPlugin,
)


__all__ = (
    "BaseModel",
    "nullable_str",
    "mapper_registry",
)

# Аннотация для необязательных строковых полей
nullable_str = Annotated[str, mapped_column(nullable=False)]

# Инициализация метаданных
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_`%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

# Инициализация SQLAlchemy-Continuum
make_versioned(user_cls=None, plugins=[ActivityPlugin(), PropertyModTrackerPlugin()])

# Создаем registry и Base с использованием metadata
mapper_registry = registry(metadata=metadata)
Base = mapper_registry.generate_base()


class BaseModel(AsyncAttrs, Base):
    """
    Базовый класс для всех моделей SQLAlchemy.

    Атрибуты:
        id (Mapped[int]): Уникальный идентификатор записи.
        created_at (Mapped[datetime]): Время создания записи.
        updated_at (Mapped[datetime]): Время последнего обновления записи.

    Методы:
        transfer_model_to_schema: Преобразует модель в схему Pydantic.
        get_value_from_secret_str: Преобразует SecretStr в обычные строки.
        to_dict: Преобразует модель в словарь.
        update: Обновляет атрибуты модели.
    """

    __abstract__ = True
    __versioned__ = {}  # Включаем версионирование для всех моделей

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), onupdate=func.now()
    )

    @declared_attr.directive
    @classmethod
    def __tablename__(cls) -> str:
        """
        Генерирует имя таблицы на основе имени класса.

        Возвращает:
            str: Имя таблицы в нижнем регистре с добавлением 's'.
        """
        return cls.__name__.lower() + "s"

    @staticmethod
    async def get_value_from_secret_str(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Преобразует все SecretStr в словаре в обычные строки.

        Аргументы:
            data (Dict[str, Any]): Словарь, который может содержать SecretStr.

        Возвращает:
            Dict[str, Any]: Словарь с преобразованными значениями.
        """
        return {
            key: value.get_secret_value() if isinstance(value, SecretStr) else value
            for key, value in data.items()
        }

    async def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует модель в словарь.

        Возвращает:
            Dict[str, Any]: Словарь с атрибутами модели.
        """
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }

    async def update(self, **kwargs) -> None:
        """
        Обновляет атрибуты модели.

        Аргументы:
            **kwargs: Пара ключ-значение для обновления атрибутов модели.
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
