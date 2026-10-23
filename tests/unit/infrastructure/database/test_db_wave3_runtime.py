"""Runtime-тесты DB-HIGH фиксов — cycle 172, Wave 3.

Каждый тест закрывает конкретный дефект из
``S3_CACHE_DB_FS_LOGGING_AUDIT_2026-10-22.md`` и **падал бы** до правки:

* HIGH-11 — circuit breaker ``db:main`` теперь стоит на CRUD-пути
  (``connection()``), а не только на ``create_session()``;
* HIGH-12 — ``pool_pre_ping`` читается из настроек, а не захардкожен;
* HIGH-13 — DSN основной БД URL-энкодит логин и пароль;
* MEDIUM-07 — ``PoolMonitor.collect_stats()`` собирает статистику
  (раньше всегда возвращал ``None`` из-за опечатки ``_async_engine``);
* MEDIUM-10 — ``max_retries`` реально применяется;
* LOW-03 — внешний session manager кэшируется.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest.importorskip("aiosqlite")

from src.backend.core.config.database import DatabaseConnectionSettings  # noqa: E402
from src.backend.core.enums.database import DatabaseTypeChoices  # noqa: E402
from src.backend.infrastructure.database.session_manager import (  # noqa: E402
    DatabaseSessionManager,
    get_external_session_manager,
)

# ── HIGH-13: URL-энкодинг DSN ───────────────────────────────────────────


@pytest.mark.parametrize(
    "password", ["p@ss:word", "pass/word#1", "100%secret", "with space", "a&b=c"]
)
def test_main_dsn_url_encodes_credentials(password: str) -> None:
    """DSN основной БД экранирует спецсимволы логина и пароля.

    Раньше пароль подставлялся сырым: ``p@ss:word`` ломал строку подключения
    — SQLAlchemy разбирал её как другой хост/путь.
    """
    settings = DatabaseConnectionSettings(
        type=DatabaseTypeChoices.postgresql,
        host="db.internal",
        port=5432,
        name="app",
        username="user",
        password=password,
    )

    url = settings.async_connection_url
    userinfo = url.split("://", 1)[1].split("@", 1)[0]

    # Пароль присутствует в URL только в закодированном виде.
    assert quote_plus(password) in userinfo, f"пароль не URL-энкодирован: {userinfo}"
    # «Сырой» пароль в userinfo отсутствует (иначе он разорвал бы DSN).
    assert password not in userinfo, f"сырой пароль попал в DSN: {url}"
    # Структура DSN не пострадала.
    assert url.startswith("postgresql+")
    assert url.endswith("@db.internal:5432/app")


def test_main_dsn_encodes_username_too() -> None:
    """Логин тоже энкодится — ``@`` в логине ломал бы DSN."""
    settings = DatabaseConnectionSettings(
        type=DatabaseTypeChoices.postgresql,
        host="db.internal",
        port=5432,
        name="app",
        username="user@corp",
        password="p",
    )

    url = settings.async_connection_url
    assert "user%40corp" in url
    assert url.endswith("@db.internal:5432/app")


# ── HIGH-12: pool_pre_ping читается из настроек ────────────────────────


def test_pool_pre_ping_is_configurable() -> None:
    """``pool_pre_ping`` берётся из настроек, а не захардкожен в ``True``.

    Раньше в ``initializer.py`` стояло ``pool_pre_ping: True``, и поле
    конфига (в т.ч. ``prod.yml``) не читалось — настройка была мёртвой.
    """
    from src.backend.infrastructure.database.database.initializer import (
        DatabaseInitializer,
    )

    def _make(pre_ping: bool) -> DatabaseInitializer:
        return DatabaseInitializer(
            settings=DatabaseConnectionSettings(
                type=DatabaseTypeChoices.postgresql,
                host="db.internal",
                port=5432,
                name="app",
                username="u",
                password="p",
                pool_pre_ping=pre_ping,
            ),
            name="probe",
        )

    assert _make(True)._engine_kwargs(is_async=True)["pool_pre_ping"] is True
    assert _make(False)._engine_kwargs(is_async=True)["pool_pre_ping"] is False


# ── HIGH-11: circuit breaker на CRUD-пути ───────────────────────────────


@pytest_asyncio.fixture
async def sqlite_manager(tmp_path: Any) -> DatabaseSessionManager:
    """Настоящий session manager поверх временной aiosqlite-БД."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_file = tmp_path / "wave3.db"

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    maker = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )

    manager = DatabaseSessionManager(session_maker=maker, db_name="wave3")
    yield manager
    await async_engine.dispose()


@pytest.mark.asyncio
async def test_connection_decorator_goes_through_breaker(
    sqlite_manager: DatabaseSessionManager,
) -> None:
    """CRUD-путь (``connection()``) проходит через circuit breaker.

    Раньше breaker оборачивал только ``create_session()``, а все 11
    методов ``SQLAlchemyRepository`` шли через ``connection()`` — то есть
    breaker ``db:main`` на основном пути не срабатывал никогда.

    Проверка сделана через подмену breaker'а на «всегда открытый»: если
    CRUD-путь его не спрашивает — исключение не всплывёт.
    """
    from contextlib import asynccontextmanager

    class _CircuitOpen(RuntimeError):
        pass

    @asynccontextmanager
    async def _always_open() -> Any:
        raise _CircuitOpen("breaker open")
        yield  # pragma: no cover — unreachable, но нужен для asynccontextmanager

    class _OpenBreaker:
        is_open = True
        state = "open"

        def guard(self) -> Any:
            return _always_open()

    sqlite_manager._breaker = _OpenBreaker()  # type: ignore[assignment]

    @sqlite_manager.connection()
    async def _query(session: AsyncSession) -> int:
        return 1

    with pytest.raises(_CircuitOpen):
        await _query()


@pytest.mark.asyncio
async def test_create_session_also_goes_through_breaker(
    sqlite_manager: DatabaseSessionManager,
) -> None:
    """``create_session()`` по-прежнему защищён breaker'ом (регрессия)."""
    from contextlib import asynccontextmanager

    class _CircuitOpen(RuntimeError):
        pass

    @asynccontextmanager
    async def _always_open() -> Any:
        raise _CircuitOpen("breaker open")
        yield  # pragma: no cover

    class _OpenBreaker:
        is_open = True
        state = "open"

        def guard(self) -> Any:
            return _always_open()

    sqlite_manager._breaker = _OpenBreaker()  # type: ignore[assignment]

    with pytest.raises(_CircuitOpen):
        async with sqlite_manager.create_session():
            pass  # pragma: no cover


# ── MEDIUM-10: max_retries реально применяется ─────────────────────────


class _BrokenSession:
    """Сессия, у которой установка соединения всегда падает."""

    def __init__(self) -> None:
        self.closed = False

    async def connection(self) -> Any:
        from sqlalchemy.exc import OperationalError

        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    async def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> "_BrokenSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest_asyncio.fixture
def _max_retries() -> Any:
    """Ставит ``max_retries = 2`` в настройках БД."""
    from src.backend.core.config.settings import settings

    original = settings.database.max_retries
    object.__setattr__(settings.database, "max_retries", 2)
    yield
    object.__setattr__(settings.database, "max_retries", original)


@pytest_asyncio.fixture
def _max_retries_zero() -> Any:
    """Ставит ``max_retries = 0`` в настройках БД."""
    from src.backend.core.config.settings import settings

    original = settings.database.max_retries
    object.__setattr__(settings.database, "max_retries", 0)
    yield
    object.__setattr__(settings.database, "max_retries", original)


@pytest.mark.asyncio
async def test_max_retries_retries_connection_failures(_max_retries: Any) -> None:
    """``max_retries`` реально повторяет установку соединения.

    Раньше настройка не читалась ни одним читателем в DB-слое: одна
    неудачная попытка — и сразу исключение.
    """
    attempts = 0

    def _session_maker() -> _BrokenSession:
        nonlocal attempts
        attempts += 1
        return _BrokenSession()

    manager = DatabaseSessionManager(
        session_maker=_session_maker,  # type: ignore[arg-type]
        db_name="wave3-broken",
    )

    with pytest.raises(Exception):
        await manager._acquire_session()

    # max_retries=2 → 3 попытки (первая + 2 повтора).
    assert attempts == 3, f"ожидалось 3 попытки, получено {attempts}"


@pytest.mark.asyncio
async def test_max_retries_zero_does_not_retry(_max_retries_zero: Any) -> None:
    """При ``max_retries = 0`` повторов нет — ровно одна попытка."""
    attempts = 0

    def _session_maker() -> _BrokenSession:
        nonlocal attempts
        attempts += 1
        return _BrokenSession()

    manager = DatabaseSessionManager(
        session_maker=_session_maker,  # type: ignore[arg-type]
        db_name="wave3-broken",
    )

    with pytest.raises(Exception):
        await manager._acquire_session()

    assert attempts == 1, f"ожидалась 1 попытка, получено {attempts}"


@pytest.mark.asyncio
async def test_retry_does_not_swallow_business_errors(_max_retries: Any) -> None:
    """Retry не превращает логическую ошибку в повторяемую.

    Повторяться должны только ошибки установки соединения
    (``OperationalError``/``InterfaceError``), а не ошибки бизнес-логики.
    """
    attempts = 0

    class _BusinessError(RuntimeError):
        pass

    def _session_maker() -> _BrokenSession:
        nonlocal attempts
        attempts += 1
        session = _BrokenSession()

        async def _connection() -> Any:
            raise _BusinessError("business rule violated")

        session.connection = _connection  # type: ignore[method-assign]
        return session

    manager = DatabaseSessionManager(
        session_maker=_session_maker,  # type: ignore[arg-type]
        db_name="wave3-broken",
    )

    with pytest.raises(_BusinessError):
        await manager._acquire_session()

    assert attempts == 1, f"бизнес-ошибка не должна повторяться, попыток: {attempts}"


# ── MEDIUM-07: PoolMonitor собирает статистику ──────────────────────────


@pytest.mark.asyncio
async def test_pool_monitor_collects_stats() -> None:
    """``PoolMonitor.collect_stats()`` возвращает статистику, а не ``None``.

    Раньше читался несуществующий атрибут ``_async_engine`` (а имя —
    ``async_engine``), ``AttributeError`` глотался, и метод **всегда**
    возвращал ``None``.
    """
    from unittest.mock import MagicMock, patch

    from src.backend.infrastructure.database.pool_monitor import PoolMonitor

    mock_pool = MagicMock()
    mock_pool.checkedin.return_value = 5
    mock_pool.checkedout.return_value = 3
    mock_pool.overflow.return_value = 0
    mock_pool.size.return_value = 10

    mock_engine = MagicMock()
    mock_engine.pool = mock_pool

    mock_initializer = MagicMock()
    # Именно настоящее имя атрибута — иначе тест повторяет опечатку.
    mock_initializer.async_engine = mock_engine

    monitor = PoolMonitor(check_interval=60)
    with patch(
        "src.backend.infrastructure.database.database.db_initializer",
        mock_initializer,
        create=True,
    ):
        stats = await monitor.collect_stats()

    assert stats is not None, "collect_stats() не должен возвращать None"
    assert stats["pool_size"] == 10
    assert stats["checked_in"] == 5
    assert stats["checked_out"] == 3
    assert stats["total_connections"] == 8
    assert stats["utilization_pct"] == 30.0


# ── LOW-03: кэширование внешнего session manager ───────────────────────


def test_external_session_manager_is_cached() -> None:
    """Внешний session manager кэшируется по имени профиля.

    Раньше каждый вызов создавал новый менеджер, а значит — новый breaker
    в общем реестре: счётчики отказов обнулялись и breaker не накапливал
    историю сбоев.
    """
    from unittest.mock import MagicMock, patch

    with patch(
        "src.backend.infrastructure.database.session_manager.get_external_db_registry"
    ) as registry:
        initializer = MagicMock()
        initializer.async_session_maker = MagicMock()
        registry.return_value.get_initializer.return_value = initializer

        first = get_external_session_manager("probe-profile")
        second = get_external_session_manager("probe-profile")

        assert first is second, "менеджер внешней БД должен кэшироваться"
