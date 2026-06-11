from __future__ import annotations
import ssl
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypeAlias

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.config.settings import settings
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.core.errors import DatabaseError
from src.backend.infrastructure.database.listeners import DatabaseListener
from src.backend.infrastructure.logging import get_logger

db_logger = get_logger("database")



DatabaseSettings: TypeAlias = (
    DatabaseConnectionSettings | ExternalDatabaseConnectionSettings
)




@lru_cache(maxsize=1)
def get_db_initializer() -> "DatabaseInitializer":
    """Lazy singleton ``DatabaseInitializer`` для main-БД (Wave 6.1)."""
    return DatabaseInitializer(settings=settings.database, name="main")



@lru_cache(maxsize=1)
def get_smart_session_manager() -> Any:
    """Lazy singleton :class:`SmartSessionManager` для main-БД (S11 K2 W2).

    Если ``settings.database.replica_dsn`` не задан — manager создаётся
    без replica и работает в single-primary режиме, что эквивалентно
    прежнему поведению ``get_main_session_manager``.
    """
    from src.backend.infrastructure.database.smart_session_manager import (
        SmartSessionManager,
    )

    bundle = get_db_initializer().as_bundle()
    return SmartSessionManager(
        primary_sessionmaker=bundle.async_session_maker,
        replica_sessionmaker=bundle.replica_session_maker,
    )



@lru_cache(maxsize=1)
def get_external_db_registry() -> "ExternalDatabaseRegistry":
    """Lazy singleton реестра внешних БД (Wave 6.1)."""
    return ExternalDatabaseRegistry(configs=settings.external_databases.profiles)



def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat импортов (Wave 6.1)."""
    if name == "db_initializer":
        return get_db_initializer()
    if name == "external_db_registry":
        return get_external_db_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")



