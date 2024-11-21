from datetime import datetime
import sys
import traceback
from typing import Annotated, Type

from annotated_types import T
from sqlalchemy import Integer, MetaData, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import (DeclarativeBase, Mapped,
                            mapped_column, declared_attr)

from gd_advanced_tools.schemas import PublicModel


__all__ = ('BaseModel',)


nullable_str = Annotated[str, mapped_column(nullable=False)]


class BaseModel(AsyncAttrs, DeclarativeBase):

    __abstract__ = True

    metadata = MetaData(
        naming_convention={
            'ix': 'ix_%(column_0_label)s',
            'uq': 'uq_%(table_name)s_%(column_0_name)s',
            'ck': 'ck_%(table_name)s_`%(constraint_name)s',
            'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
            'pk': 'pk_%(table_name)s',
        }
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now()
    )

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower() + 's'

    async def transfer_model_to_schema(self, schema: PublicModel):
        try:
            return schema.model_validate(self)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return 'Ошибка преобразования модели в схему'
