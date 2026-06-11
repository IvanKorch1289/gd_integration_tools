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




class DatabaseBundle:
    """
    Контейнер инфраструктурных объектов одной БД.

    Принцип проекта — async-first: все hot-path SQL-вызовы идут через
    ``async_engine`` / ``async_session_maker``. Sync-варианты (Wave F.3
    F.3) опциональны и поднимаются только если установлен sync-драйвер
    (``psycopg``/``oracledb``/``pysqlite``); используются библиотеками,
    которые ещё не поддерживают async (APScheduler SQLAlchemyJobStore).
    При недоступности sync-драйвера соответствующие потребители
    получают ``None`` и должны иметь fallback (memory jobstore и т.п.).

    Attributes:
        name (str): Логическое имя БД или profile_name.
        settings (DatabaseSettings): Настройки подключения.
        async_engine (AsyncEngine): Асинхронный engine (обязателен).
        async_session_maker (async_sessionmaker[AsyncSession]):
            Фабрика асинхронных сессий (обязательна).
        sync_engine (Engine | None): Синхронный engine; ``None`` если
            sync-драйвер не установлен.
        sync_session_maker (sessionmaker | None): Фабрика синхронных
            сессий; ``None`` если ``sync_engine is None``.
    """

    name: str
    settings: DatabaseSettings
    async_engine: AsyncEngine
    async_session_maker: async_sessionmaker[AsyncSession]
    sync_engine: Engine | None
    sync_session_maker: sessionmaker | None
    # S11 K2 W2 wire-up: опц. read-replica engine/sessionmaker. Если
    # ``settings.replica_dsn`` не задан — поля остаются ``None`` и
    # ``SmartSessionManager`` работает в single-primary режиме.
    replica_engine: AsyncEngine | None = None
    replica_session_maker: async_sessionmaker[AsyncSession] | None = None
