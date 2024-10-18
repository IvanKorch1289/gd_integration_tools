from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import (create_async_engine, async_sessionmaker,
                                    AsyncAttrs)
from sqlalchemy.orm import (DeclarativeBase, declared_attr,
                            Mapped, mapped_column)

from gd_advanced_tools.core.settings import database_settings as ds


class DatabaseHelper:
    """Класс создания движка с БД и фабрики сессий."""

    def __init__(self, url: str, echo: bool, pool_size: int, max_overflow: int):
        self.async_engine = create_async_engine(
            url=url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow
        )
        self.async_session_factory = async_sessionmaker(
            bind=self.async_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False
        )

    async def get_session(self) -> AsyncGenerator:
        """Функция-генератор асинхронных сессий к БД."""
        async with self.async_session_factory() as session:
            yield session
            await session.close()


db_helper = DatabaseHelper(
    url=ds.db_url_asyncpg,
    echo=ds.DB_ECHO,
    pool_size=ds.DB_POOLSIZE,
    max_overflow=ds.DB_MAXOVERFLOW
)


class Base(AsyncAttrs, DeclarativeBase):
    """ORM-базовый класс для учета метаданных."""

    __abstract__ = True

    @declared_attr.directive
    def __tablename__(self):
        return f'{self.__name__.lower()}s'

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), server_onupdate=func.now())
