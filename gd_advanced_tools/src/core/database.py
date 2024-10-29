from datetime import datetime

from sqlalchemy import TIMESTAMP, MetaData, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncAttrs
from sqlalchemy.orm import (DeclarativeBase, Mapped,
                            mapped_column, declared_attr)

from gd_advanced_tools.src.core.settings import database_settings as ds


class DatabaseInitializer:
    """Класс инициализации движка БД и получения сессий"""
    def __init__(self, url: str, echo: bool, pool_size: int, max_overflow: int):
        self.async_engine: AsyncEngine = create_async_engine(
            url=url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            future=True,
            pool_pre_ping=True
        )


DB_INIT = DatabaseInitializer(
    url=ds.db_url_asyncpg,
    echo=ds.DB_ECHO,
    pool_size=ds.DB_POOLSIZE,
    max_overflow=ds.DB_MAXOVERFLOW
)


class Base(AsyncAttrs, DeclarativeBase):
    __abstract__ = True

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_`%(constraint_name)s`",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.now()
    )

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower() + 's'
