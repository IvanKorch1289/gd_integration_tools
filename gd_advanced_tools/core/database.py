from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

from gd_advanced_tools.core.settings import settings


class DatabaseInitializer:
    """Класс инициализации движка БД и получения сессий"""
    def __init__(
        self,
        url: str,
        echo: bool,
        pool_size: int,
        max_overflow: int
    ):
        self.async_engine: AsyncEngine = create_async_engine(
            url=url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            future=True,
            pool_pre_ping=True
        )


DB_INIT = DatabaseInitializer(
    url=settings.database_settings.db_url_asyncpg,
    echo=settings.database_settings.db_echo,
    pool_size=settings.database_settings.db_poolsize,
    max_overflow=settings.database_settings.db_maxoverflow
)
