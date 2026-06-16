from __future__ import annotations

from functools import lru_cache
from typing import Any, TypeAlias

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.config.settings import settings
from src.backend.infrastructure.database.database.initializer import (
    DatabaseInitializer,  # S67 W3: fix NameError (TD-pre-existing)
)
from src.backend.infrastructure.database.database.registry import (
    ExternalDatabaseRegistry,  # S67 W3: fix NameError (TD-pre-existing)
)
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

    S145 W3: используем module-level lookup для ``get_db_initializer`` —
    иначе ``monkeypatch.setattr`` в tests/ не сможет подменить функцию
    (импорт binds name в accessors.__dict__, не в database.__dict__).
    """
    # S145 W3: use module-level lookup для monkeypatch-friendly access.
    # ``from .initializer import get_db_initializer`` binds the name в
    # accessors.__dict__ — ``monkeypatch.setattr(database, ...)`` patches
    # database.__dict__, а не accessors.__dict__. Module-level lookup
    # гарантирует test isolation.
    from src.backend.infrastructure.database import database as _db_mod
    from src.backend.infrastructure.database.smart_session_manager import (
        SmartSessionManager,
    )

    bundle = _db_mod.get_db_initializer().as_bundle()
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
