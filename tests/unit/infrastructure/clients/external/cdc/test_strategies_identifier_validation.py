"""S-17 (Wave 13, Q11): SQL-инъекция через имена таблиц/колонок в CDC.

Имена таблиц и timestamp-колонки из :class:`CDCSubscription` попадают
в SQL polling- и logminer-стратегий через f-string (bind-параметры
применяются только к значениям). Без allowlist-валидации значение
``"users; DROP TABLE x"`` превращается в исполняемый SQL.

Покрытие:
    1. Инъекционные имена отклоняются на подписке (``CDCClient.subscribe``).
    2. Инъекционные имена отклоняются стратегией (defence in depth).
    3. Валидные имена (в т.ч. ``schema.table``) принимаются.
    4. В БД уходит только валидный идентификатор (fake-connection
       перехватывает реально исполняемый SQL).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.infrastructure.clients.external.cdc._cursor import PollCursor
from src.backend.infrastructure.clients.external.cdc.client import CDCClient
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,
    CDCSubscription,
)
from src.backend.infrastructure.clients.external.cdc.strategies import (
    _LogMinerStrategy,
    _PollingStrategy,
)

# ════════════════════════════════════════════════════════════════════
# Fixtures / fakes
# ════════════════════════════════════════════════════════════════════


class _SqlHarness:
    """Перехватывает SQL, исполняемый CDC-стратегией, и останавливает цикл."""

    def __init__(self) -> None:
        self.captured: list[str] = []
        self.sub: CDCSubscription | None = None

    def stop(self) -> None:
        """Остановить polling-цикл стратегии (sub.active = False)."""
        if self.sub is not None:
            self.sub.active = False


class _FakeResult:
    """Минимальный результат ``execute()`` — пустой набор строк."""

    def fetchall(self) -> list[Any]:
        """Вернуть пустой список строк."""
        return []


class _FakeConnection:
    """Async-context-manager соединение, перехватывающее исполняемый SQL."""

    def __init__(self, harness: _SqlHarness) -> None:
        self._harness = harness

    async def __aenter__(self) -> _FakeConnection:
        """Войти в контекст соединения."""
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        """Выйти из контекста соединения без подавления исключений."""
        return False

    async def execute(self, query: Any, params: Any = None) -> _FakeResult:
        """Перехватить SQL-текст и остановить polling-цикл."""
        self._harness.captured.append(str(query))
        self._harness.stop()
        return _FakeResult()


class _FakeEngine:
    """Async engine, отдающий fake-соединения."""

    def __init__(self, harness: _SqlHarness) -> None:
        self._harness = harness

    def connect(self) -> _FakeConnection:
        """Вернуть новое fake-соединение."""
        return _FakeConnection(self._harness)


class _FakeInitializer:
    """Заглушка ``DatabaseInitializer``."""

    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def get_async_engine(self) -> _FakeEngine:
        """Вернуть fake async engine."""
        return self._engine


class _FakeRegistry:
    """Заглушка ``ExternalDatabaseRegistry``."""

    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def get_initializer(self, profile: str) -> _FakeInitializer:
        """Вернуть fake initializer (profile не важен)."""
        return _FakeInitializer(self._engine)


@pytest.fixture
def sql_harness(monkeypatch: pytest.MonkeyPatch) -> _SqlHarness:
    """Подменить реестр внешних БД на fake и вернуть harness-перехватчик."""
    harness = _SqlHarness()
    registry = _FakeRegistry(_FakeEngine(harness))
    monkeypatch.setattr(
        "src.backend.infrastructure.database.database.accessors."
        "get_external_db_registry",
        lambda: registry,
    )
    return harness


async def _noop_dispatch(sub: CDCSubscription, event: CDCEvent) -> None:
    """Заглушка dispatch-callback (события не интересуют)."""
    return None


def _polling_without_redis(monkeypatch: pytest.MonkeyPatch) -> _PollingStrategy:
    """Polling-стратегия без обращения к Redis (курсор всегда в памяти)."""
    strategy = _PollingStrategy()

    async def _cursor(key: str, default: PollCursor) -> PollCursor:
        return default

    monkeypatch.setattr(strategy, "_get_cursor", _cursor)
    return strategy


# ════════════════════════════════════════════════════════════════════
# 1. Подписка: fail-fast на инъекционных именах
# ════════════════════════════════════════════════════════════════════

INJECTION_TABLES = [
    "users; DROP TABLE x",
    "t) OR 1=1 --",
    "users' OR '1'='1",
    "users UNION SELECT password FROM accounts",
    'users" ; DELETE FROM orders; --',
]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_table", INJECTION_TABLES)
async def test_subscribe_rejects_injection_in_table(bad_table: str) -> None:
    """CDCClient.subscribe: инъекционное имя таблицы → отказ, подписки нет."""
    client = CDCClient(dlq_required=False)

    with pytest.raises(ValueError, match="identifier"):
        await client.subscribe(profile="oracle_prod", tables=[bad_table])

    assert client.list_subscriptions() == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_rejects_injection_in_timestamp_column() -> None:
    """CDCClient.subscribe: инъекционная timestamp-колонка → отказ."""
    client = CDCClient(dlq_required=False)

    with pytest.raises(ValueError, match="identifier"):
        await client.subscribe(
            profile="oracle_prod",
            tables=["orders"],
            timestamp_column="updated_at > 0; DROP TABLE x",
        )

    assert client.list_subscriptions() == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_accepts_valid_identifiers() -> None:
    """CDCClient.subscribe: валидные имена (в т.ч. schema.table) принимаются."""
    client = CDCClient(dlq_required=False)

    sub_id = await client.subscribe(
        profile="oracle_prod",
        tables=["public.orders", "_audit_log"],
        timestamp_column="updated_at",
    )

    subscriptions = client.list_subscriptions()
    assert subscriptions[0]["tables"] == ["public.orders", "_audit_log"]
    assert sub_id == subscriptions[0]["id"]

    await asyncio.sleep(0)  # дать фоновой задаче стартовать
    await client.shutdown()


# ════════════════════════════════════════════════════════════════════
# 2. Polling-стратегия: defence in depth
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_table", INJECTION_TABLES)
async def test_polling_strategy_rejects_injection_in_table(
    bad_table: str, sql_harness: _SqlHarness
) -> None:
    """Polling: инъекционное имя таблицы → отказ, SQL не исполняется."""
    sub = CDCSubscription(profile="oracle_prod", tables=[bad_table], interval=0)
    sql_harness.sub = sub
    strategy = _PollingStrategy()

    with pytest.raises(ValueError, match="identifier"):
        await strategy.run(sub, _noop_dispatch)

    assert sql_harness.captured == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_polling_strategy_rejects_injection_in_timestamp_column(
    sql_harness: _SqlHarness,
) -> None:
    """Polling: инъекционная timestamp-колонка → отказ, SQL не исполняется."""
    sub = CDCSubscription(
        profile="oracle_prod",
        tables=["orders"],
        timestamp_column="updated_at) OR 1=1 --",
        interval=0,
    )
    sql_harness.sub = sub
    strategy = _PollingStrategy()

    with pytest.raises(ValueError, match="identifier"):
        await strategy.run(sub, _noop_dispatch)

    assert sql_harness.captured == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_polling_strategy_executes_sql_with_valid_identifier(
    monkeypatch: pytest.MonkeyPatch, sql_harness: _SqlHarness
) -> None:
    """Polling: валидное имя таблицы → в БД уходит только валидный identifier."""
    sub = CDCSubscription(
        profile="oracle_prod",
        tables=["public.orders"],
        timestamp_column="updated_at",
        interval=0,
    )
    sql_harness.sub = sub
    strategy = _polling_without_redis(monkeypatch)

    await strategy.run(sub, _noop_dispatch)

    assert len(sql_harness.captured) == 1
    sql = sql_harness.captured[0]
    assert "SELECT * FROM public.orders" in sql
    # ADR-0384: составной курсор (ts, PK) — условие на границе батча.
    assert "WHERE updated_at >= :last_ts" in sql
    assert "ORDER BY updated_at" in sql
    assert "DROP" not in sql.upper()


# ════════════════════════════════════════════════════════════════════
# 3. LogMiner-стратегия
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_logminer_strategy_rejects_quote_in_table(
    sql_harness: _SqlHarness,
) -> None:
    """LogMiner: одинарная кавычка в имени таблицы → отказ."""
    sub = CDCSubscription(
        profile="oracle_prod",
        tables=["USERS' OR '1'='1"],
        strategy="logminer",
        interval=0,
    )
    sql_harness.sub = sub
    strategy = _LogMinerStrategy()

    with pytest.raises(ValueError, match="identifier"):
        await strategy.run(sub, _noop_dispatch)

    assert sql_harness.captured == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_logminer_strategy_executes_sql_with_valid_identifiers(
    sql_harness: _SqlHarness,
) -> None:
    """LogMiner: валидные имена → TABLE_NAME IN собран из безопасных литералов."""
    sub = CDCSubscription(
        profile="oracle_prod",
        tables=["orders", "customers"],
        strategy="logminer",
        interval=0,
    )
    sql_harness.sub = sub
    strategy = _LogMinerStrategy()

    await strategy.run(sub, _noop_dispatch)

    # ADR-0384: START_LOGMNR → SELECT → END_LOGMNR.
    assert len(sql_harness.captured) == 3
    assert "DBMS_LOGMNR.START_LOGMNR" in sql_harness.captured[0]
    sql = sql_harness.captured[1]
    assert "TABLE_NAME IN ('ORDERS', 'CUSTOMERS')" in sql
    assert "OR '1'='1" not in sql
    assert "DBMS_LOGMNR.END_LOGMNR" in sql_harness.captured[2]


# ════════════════════════════════════════════════════════════════════
# 4. Валидатор идентификаторов (allowlist)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.parametrize(
    "value", ["orders", "_audit", "public.orders", "db.schema.table", "T1"]
)
def test_validate_identifier_accepts_safe_values(value: str) -> None:
    """Allowlist-валидатор принимает обычные SQL-идентификаторы."""
    from src.backend.infrastructure.clients.external.cdc._identifiers import (
        validate_identifier,
    )

    assert validate_identifier(value, context="test") == value


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "",
        "1orders",
        "orders; DROP TABLE x",
        "orders customers",
        "orders'",
        'orders"',
        "orders--",
        "orders/*x*/",
        "a.b.c.d",
        "orders\n",
    ],
)
def test_validate_identifier_rejects_unsafe_values(value: str) -> None:
    """Allowlist-валидатор отклоняет всё, что не является identifier-ом."""
    from src.backend.infrastructure.clients.external.cdc._identifiers import (
        validate_identifier,
    )

    with pytest.raises(ValueError, match="identifier"):
        validate_identifier(value, context="test")


@pytest.mark.unit
def test_validate_identifier_rejects_non_string() -> None:
    """Не-строки отклоняются (type confusion guard)."""
    from src.backend.infrastructure.clients.external.cdc._identifiers import (
        validate_identifier,
    )

    with pytest.raises(ValueError, match="identifier"):
        validate_identifier(123, context="test")  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "orders",
        "_audit",
        "T1",
        "",
        "1orders",
        "orders; DROP TABLE x",
        "orders customers",
        "orders'",
        "orders\n",
    ],
)
def test_validate_identifier_follows_canonical_for_single_segment(value: str) -> None:
    """Одиночный сегмент решается каноном ``core.utils.sql_identifiers``.

    CDC-обёртка добавляет только dotted-формы (``schema.name``) — правило
    сегмента общее (ADR-0112), дубль regex'а в CDC-модуле не нужен.
    """
    from src.backend.core.utils.sql_identifiers import (
        validate_identifier as canonical_validate_identifier,
    )
    from src.backend.infrastructure.clients.external.cdc._identifiers import (
        validate_identifier,
    )

    def _accepts(validator: object, candidate: str) -> bool:
        try:
            validator(candidate, context="test")  # type: ignore[operator]
        except ValueError:
            return False
        return True

    assert _accepts(validate_identifier, value) == _accepts(
        canonical_validate_identifier, value
    )


@pytest.mark.unit
def test_escape_sql_literal_doubles_single_quote() -> None:
    """Строковый литерал экранируется (defence in depth для LogMiner)."""
    from src.backend.infrastructure.clients.external.cdc._identifiers import (
        escape_sql_literal,
    )

    assert escape_sql_literal("USERS' OR '1'='1") == "USERS'' OR ''1''=''1"


@pytest.mark.unit
def test_timestamp_column_default_is_valid() -> None:
    """Дефолтная timestamp-колонка проходит валидацию."""
    from src.backend.infrastructure.clients.external.cdc._identifiers import (
        validate_subscription_identifiers,
    )

    sub = CDCSubscription(profile="oracle_prod", tables=["orders"])
    validate_subscription_identifiers(sub)


@pytest.mark.unit
def test_validate_subscription_identifiers_rejects_bad_table() -> None:
    """Валидация подписки отклоняет инъекционное имя таблицы."""
    from src.backend.infrastructure.clients.external.cdc._identifiers import (
        validate_subscription_identifiers,
    )

    sub = CDCSubscription(profile="oracle_prod", tables=["orders", "bad; DROP TABLE x"])

    with pytest.raises(ValueError, match="identifier"):
        validate_subscription_identifiers(sub)
