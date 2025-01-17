import sys
import traceback
from datetime import datetime
from typing import Annotated, Any, Dict, Type

from pydantic import SecretStr
from sqlalchemy import Integer, MetaData, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, registry

from backend.base.schemas import PublicSchema


__all__ = ("BaseModel",)


# Аннотация для необязательных строковых полей
nullable_str = Annotated[str, mapped_column(nullable=False)]

# Создаем registry
mapper_registry = registry()

# Базовый класс
Base = mapper_registry.generate_base()


class BaseModel(AsyncAttrs, Base):
    """
    Базовый класс для всех моделей SQLAlchemy.

    Атрибуты:
        __abstract__ (bool): Указывает, что это абстрактный класс.
        metadata (MetaData): Метаданные для таблиц с кастомными соглашениями именования.
        id (Mapped[int]): Первичный ключ таблицы.
        created_at (Mapped[datetime]): Время создания записи.
        updated_at (Mapped[datetime]): Время последнего обновления записи.
    """

    __abstract__ = True

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_`%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), onupdate=func.now()
    )

    @declared_attr.directive
    def __tablename__(cls) -> str:
        """
        Генерация имени таблицы на основе имени класса.

        Возвращает:
            str: Имя таблицы в нижнем регистре с добавлением 's' в конце.
        """
        return cls.__name__.lower() + "s"

    async def transfer_model_to_schema(
        self, schema: Type[PublicSchema]
    ) -> PublicSchema:
        """
        Преобразует модель в схему Pydantic.

        Аргументы:
            schema (Type[PublicSchema]): Класс схемы Pydantic.

        Возвращает:
            PublicSchema: Экземпляр схемы Pydantic.

        Исключения:
            Выводит traceback в случае ошибки и возвращает словарь с ошибкой.
        """
        try:
            return schema.model_validate(self)
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return {"Ошибка преобразования модели в схему": ex}

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
