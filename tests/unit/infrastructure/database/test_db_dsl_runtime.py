"""Runtime-тесты DB-DSL поверхности — cycle 172.

Эти дефекты были невидимы, потому что вся DB-DSL поверхность падала на
первом же обращении к DI-провайдеру, а тестов, которые её дёргали, не было.
Здесь она впервые исполняется **по-настоящему** — на настоящем
``aiosqlite`` и настоящем ``DatabaseQueryProcessor``, без моков.

Покрывает:

* CRITICAL-07 — ``get_db_manager_provider()`` резолвится (раньше
  ``AttributeError`` на каждом ``db_query`` / ``db_insert`` / ``db_update`` /
  ``db_upsert`` / ``db_delete``);
* CRITICAL-08 — ``DbCrudProcessor`` больше не выбрасывает bind-параметры,
  поэтому INSERT/UPDATE/UPSERT/DELETE реально применяются;
* CRITICAL-09 — ``ssl_mode`` действительно включает TLS (раньше TLS
  включался только при ``ca_bundle``, то есть в prod при
  ``ssl_mode: require`` + ``ca_bundle: null`` соединение было открытым);
* CRITICAL-10 — resilience-цепочки отказоустойчивости импортируются
  (раньше ``ImportError`` по отсутствующему ``get_db_session``);
* ``validate_sql`` по-прежнему блокирует DDL и multi-statement.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio

pytest.importorskip("aiosqlite")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402

from src.backend.core.config.database import DatabaseConnectionSettings  # noqa: E402
from src.backend.dsl.engine.context import ExecutionContext  # noqa: E402
from src.backend.dsl.engine.exchange import (  # noqa: E402
    Exchange,
    ExchangeStatus,
    Message,
)
from src.backend.dsl.engine.processors.components.databasequeryprocessor import (  # noqa: E402
    DatabaseQueryProcessor,
)
from src.backend.infrastructure.database.database.initializer import (  # noqa: E402
    DatabaseInitializer,
)

# ── CRITICAL-07: DI-провайдер ───────────────────────────────────────────


def test_db_manager_provider_resolves() -> None:
    """``get_db_manager_provider()`` возвращает рабочий callable, а не падает.

    Раньше: ``AttributeError: module '...database.accessors' has no attribute
    'get_db_manager'`` — на КАЖДЫЙ вызов, то есть вся DB-DSL была мертва.
    """
    from src.backend.core.di.providers.db import get_db_manager_provider

    provider = get_db_manager_provider()
    assert callable(provider), "провайдер должен вернуть callable"

    db = provider()
    assert hasattr(db, "get_async_engine"), (
        f"{type(db).__name__} не умеет отдавать engine — вызывающий код "
        "ожидает get_async_engine()"
    )


def test_resilience_chains_import() -> None:
    """Failover-цепочки импортируются и строят primary/fallback.

    Раньше: ``ImportError: cannot import name 'get_db_session'`` в
    ``database_chain`` / ``audit_chain`` / ``mongo_chain``.
    """
    from src.backend.infrastructure.database.database import get_db_session

    assert callable(get_db_session)

    from src.backend.infrastructure.resilience.components import (
        audit_chain,
        database_chain,
        mongo_chain,
    )

    primary = database_chain.build_database_primary()
    assert callable(primary)
    assert "sqlite_ro" in database_chain.build_database_fallbacks()
    # Цепочки, которые импортировали get_db_session, тоже должны грузиться.
    assert audit_chain is not None
    assert mongo_chain is not None


# ── CRITICAL-09: ssl_mode действительно включает TLS ────────────────────


def _pg_settings(ssl_mode: str | None, ca_bundle: str | None = None) -> Any:
    return DatabaseConnectionSettings(
        type="postgresql",
        host="localhost",
        port=5432,
        name="appdb",
        username="user",
        password="secret",  # noqa: S106 — тестовые настройки, без реальной БД
        ssl_mode=ssl_mode,
        ca_bundle=ca_bundle,
        pool_size=1,
        max_overflow=1,
        pool_recycle=60,
        pool_timeout=10,
        connect_timeout=5,
        command_timeout=5,
        max_retries=1,
        circuit_breaker_max_failures=3,
        circuit_breaker_reset_timeout=30,
        slow_query_threshold=1.0,
    )


def _connect_args(settings: Any, *, is_async: bool = True) -> dict[str, Any]:
    initializer = DatabaseInitializer.__new__(DatabaseInitializer)
    initializer.settings = settings
    return initializer._get_connect_args(is_async=is_async)


@pytest.mark.parametrize("ssl_mode", ["require", "verify-ca", "verify-full"])
def test_ssl_mode_enables_tls(ssl_mode: str) -> None:
    """Prod-конфиг (``ssl_mode: require``, ``ca_bundle: null``) даёт TLS.

    Раньше TLS включался **только** при непустом ``ca_bundle``, поэтому при
    ``ca_bundle: null`` из prod.yml соединение уходило без шифрования, несмотря
    на объявленный ``ssl_mode: require``.
    """
    args = _connect_args(_pg_settings(ssl_mode))

    assert "ssl" in args, f"ssl_mode={ssl_mode!r} не включил TLS"
    context = args["ssl"]
    # Проект запрещает ssl.CERT_NONE / check_hostname=False (CLAUDE.md, V1).
    assert context.check_hostname is True, (
        f"ssl_mode={ssl_mode!r} отключил проверку hostname — "
        "запрещено правилом V1"
    )
    assert context.verify_mode.name != "CERT_NONE", (
        f"ssl_mode={ssl_mode!r} отключил проверку сертификата — "
        "запрещено правилом V1"
    )


@pytest.mark.parametrize("ssl_mode", ["disable", "allow"])
def test_ssl_mode_disable_means_no_tls(ssl_mode: str) -> None:
    """Явное отключение TLS уважается (dev-профили)."""
    assert "ssl" not in _connect_args(_pg_settings(ssl_mode))


def test_unknown_ssl_mode_is_rejected() -> None:
    """Неизвестный режим — ошибка конфигурации, а не молчаливое соединение."""
    with pytest.raises(ValueError, match="Unsupported ssl_mode"):
        _connect_args(_pg_settings("totally-bogus"))


# ── CRITICAL-08: реальное исполнение DB-DSL ─────────────────────────────


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)"))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_manager(sqlite_engine: AsyncEngine):
    """Подменяет DB-manager на обёртку над настоящим aiosqlite engine.

    Используется штатный проектный хук ``set_db_manager_provider`` — именно он
    проверяет ``DatabaseQueryProcessor`` (он импортирует провайдер из
    ``di.providers.cache``, который ре-экспортирует ``di.providers.db``, так что
    ``monkeypatch`` на модуле провайдера не долетел бы).
    """

    class _Manager:
        def get_async_engine(self) -> AsyncEngine:
            return sqlite_engine

    from src.backend.core.di.providers import db as db_provider
    from src.backend.core.di.providers.db import set_db_manager_provider

    set_db_manager_provider(_Manager)
    try:
        yield _Manager
    finally:
        # Снимаем override, а не переустанавливаем его — иначе подмена
        # протекла бы на соседние тесты в этой же сессии.
        db_provider._overrides.pop("db_manager", None)


def _exchange(body: Any = None) -> Exchange[Any]:
    ex: Exchange[Any] = Exchange()
    if body is not None:
        ex.in_message = Message(body=body)
    return ex


def _assert_ok(exchange: Exchange[Any]) -> None:
    """Провалившийся шаг ДБЛЖЕН валить тест, а не молча проходить дальше."""
    assert exchange.status != ExchangeStatus.failed, (
        f"шаг упал: {exchange.error}"
    )


@pytest.mark.asyncio
async def test_db_query_processor_executes_select(db_manager: Any) -> None:
    """``db_query`` реально исполняет SELECT и кладёт строки в exchange."""
    engine = db_manager().get_async_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO widgets (name) VALUES ('gamma'), ('alpha')")
        )

    processor = DatabaseQueryProcessor(
        sql="SELECT id, name FROM widgets ORDER BY id",
        params_from_body=False,
        result_property="rows",
    )
    exchange = _exchange()

    await processor.process(exchange, ExecutionContext())

    _assert_ok(exchange)
    assert exchange.get_property("rows") == [
        {"id": 1, "name": "gamma"},
        {"id": 2, "name": "alpha"},
    ]


@pytest.mark.asyncio
async def test_db_crud_insert_binds_parameters(db_manager: Any) -> None:
    """``db_crud`` INSERT применяется — bind-параметры больше не теряются.

    Раньше ``sql, _params = build_insert_sql(...)`` отбрасывал параметры,
    а процессор брал их из тела exchange; несвязанные ``:name`` давали
    ``StatementError``. Теперь параметры передаются явно.
    """
    from src.backend.dsl.engine.processors.db_crud import DbCrudProcessor

    processor = DbCrudProcessor(
        operation="INSERT", table="widgets", data={"name": "alpha"}
    )
    exchange = _exchange()

    await processor.process(exchange, ExecutionContext())

    _assert_ok(exchange)

    result = exchange.get_property("db_crud_result")
    assert result == {"rowcount": 1}, f"неожиданный результат INSERT: {result!r}"

    # Строка действительно записалась — а не просто вернулся rowcount.
    engine = db_manager().get_async_engine()
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT name FROM widgets"))).scalars().all()
    assert list(rows) == ["alpha"], f"INSERT не применился: {rows!r}"


@pytest.mark.asyncio
async def test_db_crud_update_binds_parameters(db_manager: Any) -> None:
    """UPDATE с where-параметрами применяется."""
    from src.backend.dsl.engine.processors.db_crud import DbCrudProcessor

    sqlite_engine = db_manager().get_async_engine()
    async with sqlite_engine.begin() as conn:
        await conn.execute(text("INSERT INTO widgets (name) VALUES ('before')"))

    processor = DbCrudProcessor(
        operation="UPDATE", table="widgets", data={"name": "after"}, where={"id": 1}
    )
    exchange = _exchange()
    await processor.process(exchange, ExecutionContext())

    _assert_ok(exchange)

    async with sqlite_engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM widgets WHERE id = 1"))
        assert result.scalar_one() == "after"


@pytest.mark.asyncio
async def test_db_crud_delete_binds_parameters(db_manager: Any) -> None:
    """DELETE с where-параметрами применяется."""
    from src.backend.dsl.engine.processors.db_crud import DbCrudProcessor

    sqlite_engine = db_manager().get_async_engine()
    async with sqlite_engine.begin() as conn:
        await conn.execute(text("INSERT INTO widgets (name) VALUES ('doomed')"))

    processor = DbCrudProcessor(
        operation="DELETE", table="widgets", where={"id": 1}
    )
    exchange = _exchange()
    await processor.process(exchange, ExecutionContext())

    _assert_ok(exchange)

    async with sqlite_engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM widgets"))
        assert result.scalar_one() == 0


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE widgets",
        "CREATE TABLE x (id INT)",
        "SELECT 1; DROP TABLE widgets",
        "TRUNCATE TABLE widgets",
    ],
)
def test_validate_sql_still_blocks_dangerous(sql: str) -> None:
    """Включение явных bind-параметров не должно ослаблять валидацию SQL."""
    with pytest.raises(ValueError):
        DatabaseQueryProcessor._validate_sql(sql)
