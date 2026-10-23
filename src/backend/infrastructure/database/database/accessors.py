from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.config.settings import settings
from src.backend.core.logging import get_logger
from src.backend.infrastructure.database.database.initializer import (
    DatabaseInitializer,  # S67 W3: fix NameError (TD-pre-existing)
)
from src.backend.infrastructure.database.database.registry import (
    ExternalDatabaseRegistry,  # S67 W3: fix NameError (TD-pre-existing)
)

db_logger = get_logger("database")


type DatabaseSettings = DatabaseConnectionSettings | ExternalDatabaseConnectionSettings


@lru_cache(maxsize=1)
def get_db_initializer() -> DatabaseInitializer:
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
def get_external_db_registry() -> ExternalDatabaseRegistry:
    """Lazy singleton реестра внешних БД (Wave 6.1)."""
    return ExternalDatabaseRegistry(configs=settings.external_databases.profiles)  # type: ignore[arg-type]  # R2.MYPY: Callable[[],dict]


@lru_cache(maxsize=1)
def get_db_manager() -> DatabaseInitializer:
    """DB-менеджер main-БД — тот же singleton, что и :func:`get_db_initializer`.

    Cycle 172 (CRITICAL-07): функция **не существовала**, хотя на неё ссылались
    ``core/di/providers/db.py::get_db_manager_provider`` и
    ``DatabaseQueryProcessor``. Итог был такой: ``module.get_db_manager``
    бросал ``AttributeError``, поэтому **каждый** DSL-шаг
    ``db_query`` / ``db_insert`` / ``db_update`` / ``db_upsert`` / ``db_delete``
    падал в ``exchange.fail(...)``. Вся DB-DSL поверхность была мертва.

    Возвращается :class:`DatabaseInitializer`, потому что именно у него есть
    ``get_async_engine()`` — этого и ждёт вызывающий код (и все остальные
    места, которые берут engine напрямую: ``setup_infra/pools.py``,
    ``setup_infra/health.py``, ``processors/storage_ext.py``,
    ``processors/ml_inference.py``).

    Отдельное имя сохранено, потому что оно часть публичной DI-контракции:
    ``get_db_manager_provider()`` возвращает ссылку на этот callable, и тесты
    подменяют его через ``set_db_manager_provider``.
    """
    return get_db_initializer()


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Async context manager, отдающий сессию main-БД.

    Cycle 172 (CRITICAL-10): функции **не существовало**, хотя из неё
    импортировали три resilience-цепочки отказоустойчивости:

    * ``resilience/components/database_chain.py`` — PG → SQLite read-only
      fallback;
    * ``resilience/components/audit_chain.py``;
    * ``resilience/components/mongo_chain.py``.

    Любая из них падала с ``ImportError`` вместо деградации — то есть сам
    механизм failover по БД не работал никогда.

    Сессия коммитится при успешном выходе и откатывается при исключении,
    что соответствует семантике ``DatabaseSessionManager.transaction()``.
    """
    bundle = get_db_initializer().as_bundle()
    session = bundle.async_session_maker()
    try:
        yield session
    except BaseException:
        await session.rollback()
        await session.close()
        raise
    else:
        await session.commit()
        await session.close()


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat импортов (Wave 6.1)."""
    if name == "db_initializer":
        return get_db_initializer()
    if name == "external_db_registry":
        return get_external_db_registry()
    if name == "get_db_manager":
        return get_db_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
