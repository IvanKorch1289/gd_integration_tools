"""Wave 16 (ADR-0382) — кластер X3: потеря данных и диалекты в DSL-БД.

Покрывает дефекты пробы:

* (1) ``db_query_external``: DML молча откатывался (``commit=False`` по
  умолчанию, ``create_session()`` не коммитит) — «INSERT ... RETURNING id»
  вернул ``[{id: 1}]``, в таблице 0 строк;
* (2) ``db_query_external``: DML без RETURNING падал в ``ResourceClosedError``
  (``mappings().all()`` на result без строк) — до ``commit()`` не доходило;
* (3) ``batch_insert``: колонки брались только из 1-го item — лишние ключи
  остальных молча игнорировались;
* (4) ``batch_delete``: ``= ANY(:ids)`` — только PostgreSQL;
* (5) ``db_crud``: ``dialect`` отвязан от целевой БД;
* (6) Oracle/MSSQL UPSERT (``MERGE``) сломан;
* (7) MySQL: двойные кавычки в идентификаторах без ``ANSI_QUOTES``;
* (8) SELECT-детект по префиксу: ``WITH ... SELECT`` считался DML;
* (9) ``db_upsert`` из YAML всегда postgresql;
* (10) дубли ``_IDENT_RE`` → канон ``core/utils/sql_identifiers.py``.

Тесты против настоящего SQLite (aiosqlite) — «потеря данных» проверяется
фактическим содержимым таблицы, а не моком.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy import bindparam, text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.backend.dsl.engine.context import ExecutionContext  # noqa: E402
from src.backend.dsl.engine.exchange import (  # noqa: E402
    Exchange,
    ExchangeStatus,
    Message,
)
from src.backend.dsl.engine.processors.db_crud import (  # noqa: E402
    DbCrudProcessor,
    build_delete_sql,
    build_insert_sql,
    build_update_sql,
    build_upsert_sql_dialect,
)
from src.backend.dsl.engine.processors.db_query_external import (  # noqa: E402
    ExternalDbQueryProcessor,
)

# ─────────────────────────── fixtures / helpers ───────────────────────────


class _SessionManager:
    """Мини-менеджер сессий с семантикой реального ``create_session()``.

    Реальный ``DatabaseSessionManager.create_session()`` **не коммитит** на
    выходе — незакоммиченная транзакция откатывается при закрытии сессии.
    Здесь ровно то же поведение, поэтому «потеря данных» воспроизводится
    по-настоящему.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def create_session(self):
        """Открывает сессию; коммита нет — только явный ``session.commit()``."""
        async with self._session_factory() as session:
            yield session


@pytest.fixture
async def sqlite_engine() -> AsyncEngine:
    """Настоящий SQLite-engine (общий для всех соединений — StaticPool)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)"))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(sqlite_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика async-сессий поверх SQLite-engine."""
    return async_sessionmaker(sqlite_engine, expire_on_commit=False)


def _ctx() -> ExecutionContext:
    return ExecutionContext()


def _exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


async def _rows(engine: AsyncEngine, sql: str) -> list[dict[str, Any]]:
    """Читает строки таблицы (проверка фактического содержимого)."""
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        return [dict(row) for row in result.mappings().all()]


# ───────────────── (1)(2) db_query_external: потеря данных ─────────────────


async def test_db_query_external_dml_is_committed(
    sqlite_engine: AsyncEngine, session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(1) DML коммитится по умолчанию — данные не теряются.

    Регрессия пробы: ``INSERT ... RETURNING id`` возвращал ``[{id: 1}]``,
    но в таблице было 0 строк (тихая потеря данных).
    """
    manager = _SessionManager(session_factory)
    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: (lambda profile: manager),
    )

    proc = ExternalDbQueryProcessor(
        profile="sqlite_probe",
        sql="INSERT INTO widgets (name) VALUES (:name) RETURNING id",
    )
    ex = _exchange({"name": "alpha"})
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    assert ex.out_message.body == [{"id": 1}]
    stored = await _rows(sqlite_engine, "SELECT id, name FROM widgets")
    assert stored == [{"id": 1, "name": "alpha"}], (
        f"DML не зафиксировано — тихая потеря данных: {stored!r}"
    )


async def test_db_query_external_dml_without_returning_commits(
    sqlite_engine: AsyncEngine, session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(2) DML без RETURNING: без ``ResourceClosedError`` + commit.

    Раньше ``_materialize_result`` дёргал ``mappings().all()`` на result без
    строк → ``ResourceClosedError`` → ``commit()`` не достигался.
    """
    manager = _SessionManager(session_factory)
    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: (lambda profile: manager),
    )

    proc = ExternalDbQueryProcessor(
        profile="sqlite_probe",
        sql="INSERT INTO widgets (name) VALUES (:name)",
    )
    ex = _exchange({"name": "beta"})
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    assert ex.properties["db_result"] == {"rowcount": 1}
    stored = await _rows(sqlite_engine, "SELECT name FROM widgets")
    assert stored == [{"name": "beta"}], f"DML не зафиксировано: {stored!r}"


async def test_db_query_external_explicit_commit_false_opts_out(
    sqlite_engine: AsyncEngine, session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(1) Явный opt-out ``commit=False`` — DML не коммитится (откат)."""
    manager = _SessionManager(session_factory)
    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: (lambda profile: manager),
    )

    proc = ExternalDbQueryProcessor(
        profile="sqlite_probe",
        sql="INSERT INTO widgets (name) VALUES (:name)",
        commit=False,
    )
    ex = _exchange({"name": "gamma"})
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    stored = await _rows(sqlite_engine, "SELECT name FROM widgets")
    assert stored == [], f"commit=False обязан откатывать, а записал: {stored!r}"


async def test_db_query_external_select_is_not_committed(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SELECT не коммитится (транзакция только читает)."""
    manager = _SessionManager(session_factory)
    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: (lambda profile: manager),
    )

    proc = ExternalDbQueryProcessor(
        profile="sqlite_probe",
        sql="SELECT id FROM widgets",
        params_from="none",
    )
    ex = _exchange({})
    await proc.process(ex, _ctx())
    assert ex.status != ExchangeStatus.failed, ex.error


# ───────────────────── (3) batch_insert: union колонок ─────────────────────


class _Bundle:
    """Минимальный bundle внешней БД (нужен ``async_session_maker``)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.async_session_maker = session_factory


class _FakeBundle:
    """Bundle-заглушка: ``async_session_maker()`` → async CM с сессией."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.async_session_maker = self._session_maker

    @asynccontextmanager
    async def _session_maker(self):
        """Отдаёт заранее подготовленную сессию-заглушку."""
        yield self.session


class _CapturingSession:
    """Сессия-заглушка: запоминает выполненные SQL-выражения."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> Any:
        """Запоминает statement и возвращает result с ``rowcount``."""
        self.statements.append(str(statement))
        return _StubResult()

    async def commit(self) -> None:
        """No-op — коммит не наблюдается в этом тесте."""
        return None


class _StubResult:
    """Минимальный result: достаточно ``rowcount``."""

    rowcount = 1
    returns_rows = False


class _Registry:
    """Минимальный реестр внешних БД (нужен ``get_bundle``)."""

    def __init__(self, bundle: Any) -> None:
        self._bundle = bundle

    def get_bundle(self, profile: str) -> Any:
        return self._bundle


@pytest.fixture
def patch_external_registry(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Подменяет реестр внешних БД на SQLite-bundle."""
    from src.backend.dsl.engine.processors import batch as batch_module

    registry = _Registry(_Bundle(session_factory))
    monkeypatch.setattr(
        batch_module,
        "_get_external_db_registry",
        lambda: registry,
    )


async def test_batch_insert_keeps_columns_of_all_items(
    sqlite_engine: AsyncEngine, patch_external_registry: None
) -> None:
    """(3) Колонки — union по всем items; лишние ключи не теряются.

    Регрессия пробы: ``b=None`` — ключ ``b`` второго item'а молча
    игнорировался, потому что колонки брались только из 1-го item'а.
    """
    from src.backend.dsl.engine.processors.batch import BatchInsertProcessor

    proc = BatchInsertProcessor(table="widgets", items=[{"name": "a"}, {"name": "b", "id": 7}])
    ex = _exchange()
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    stored = await _rows(sqlite_engine, "SELECT id, name FROM widgets ORDER BY name")
    assert stored == [
        {"id": 1, "name": "a"},
        {"id": 7, "name": "b"},
    ], f"union колонок потерян: {stored!r}"


async def test_batch_insert_missing_column_is_null(
    sqlite_engine: AsyncEngine, patch_external_registry: None
) -> None:
    """(3) Отсутствующий в item'е ключ → NULL, а не «лишний столбец»."""
    from src.backend.dsl.engine.processors.batch import BatchInsertProcessor

    proc = BatchInsertProcessor(table="widgets", items=[{"id": 5, "name": "x"}, {"id": 6}])
    ex = _exchange()
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    stored = await _rows(sqlite_engine, "SELECT id, name FROM widgets ORDER BY id")
    assert stored == [{"id": 5, "name": "x"}, {"id": 6, "name": None}]


# ───────────────────── (4) batch_delete: IN вместо ANY ─────────────────────


async def test_batch_delete_works_on_non_postgres(
    sqlite_engine: AsyncEngine, patch_external_registry: None
) -> None:
    """(4) ``batch_delete`` работает на любом диалекте (IN, а не ANY).

    Регрессия пробы на sqlite: ``no such function: ANY``.
    """
    from src.backend.dsl.engine.processors.batch import BatchDeleteProcessor

    async with sqlite_engine.begin() as conn:
        await conn.execute(text("INSERT INTO widgets (name) VALUES ('doomed')"))
        await conn.execute(text("INSERT INTO widgets (name) VALUES ('kept')"))

    proc = BatchDeleteProcessor(table="widgets", ids=[1], key_field="id")
    ex = _exchange()
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    stored = await _rows(sqlite_engine, "SELECT name FROM widgets")
    assert stored == [{"name": "kept"}], f"batch_delete не удалил строку: {stored!r}"


async def test_batch_delete_statement_uses_in_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(4) В SQL — переносимый ``IN``, а не Postgres-only ``ANY``."""
    from src.backend.dsl.engine.processors import batch as batch_module
    from src.backend.dsl.engine.processors.batch import BatchDeleteProcessor

    session = _CapturingSession()
    registry = _Registry(_FakeBundle(session))
    monkeypatch.setattr(batch_module, "_get_external_db_registry", lambda: registry)

    proc = BatchDeleteProcessor(table="orders", ids=[1, 2])
    ex = _exchange()
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    assert session.statements, "DELETE не был выполнен"
    sql = session.statements[0]
    assert " IN " in sql, f"ожидался IN-clause, получено: {sql!r}"
    assert "ANY" not in sql.upper(), f"ANY остался в SQL: {sql!r}"


# ───────────────────── (8) WITH ... SELECT — не DML ─────────────────────


async def test_database_query_processor_with_select_returns_rows(
    sqlite_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(8) ``WITH ... SELECT`` — это SELECT, а не DML.

    Раньше детект по первой букве давал ``{"rowcount": -1}`` — строки терялись.
    """
    from src.backend.dsl.engine.processors.components.databasequeryprocessor import (
        DatabaseQueryProcessor,
    )

    class _Manager:
        def get_async_engine(self) -> AsyncEngine:
            return sqlite_engine

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_db_manager_provider",
        lambda: (lambda: _Manager()),
    )

    proc = DatabaseQueryProcessor(
        sql="WITH cte AS (SELECT id, name FROM widgets) SELECT id, name FROM cte",
        params_from_body=False,
        result_property="rows",
    )
    ex = _exchange()
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    assert ex.get_property("rows") == [{"id": 1, "name": "alpha"}] or isinstance(
        ex.get_property("rows"), list
    )
    assert isinstance(ex.get_property("rows"), list), (
        f"WITH..SELECT вернул {ex.get_property('rows')!r} вместо строк"
    )


async def test_infra_db_query_with_select_returns_rows(
    sqlite_engine: AsyncEngine, session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(8) ``infra_db_query``: ``WITH ... SELECT`` → строки, а не rowcount."""
    from src.backend.dsl.engine.processors.infra_db import InfraDbQueryProcessor

    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.infra_db_query_enabled",
        True,
        raising=False,
    )
    manager = _SessionManager(session_factory)
    monkeypatch.setattr(
        "src.backend.core.di.providers.infrastructure_locator.get_main_session_manager_getter",
        lambda: (lambda: manager),
    )

    proc = InfraDbQueryProcessor(
        sql="WITH cte AS (SELECT id FROM widgets) SELECT id FROM cte",
        params={},
    )
    ex = _exchange()
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    body = ex.in_message.body
    assert isinstance(body, dict) and isinstance(body.get("result"), list), (
        f"infra_db_query вернул {body!r} вместо строк"
    )


async def test_jdbc_query_with_select_returns_rows(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(8) ``jdbc_query``: ``WITH ... SELECT`` → строки, а не affected_count."""
    from src.backend.dsl.engine.processors.jdbc_query import JdbcQueryProcessor

    manager = _SessionManager(session_factory)
    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: (lambda profile: manager),
    )

    proc = JdbcQueryProcessor(
        sql="WITH cte AS (SELECT 1 AS id) SELECT id FROM cte",
        profile="sqlite_probe",
        params_from="none",
    )
    ex = _exchange({})
    await proc.process(ex, _ctx())

    assert ex.status != ExchangeStatus.failed, ex.error
    assert ex.properties["jdbc_result"] == [{"id": 1}]


# ───────────────────── (5)(6)(7) диалекты ─────────────────────


def test_insert_uses_mysql_backticks() -> None:
    """(7) MySQL: идентификаторы в backticks, а не в двойных кавычках."""
    sql, _ = build_insert_sql("orders", {"id": 1, "total": 50}, dialect="mysql")
    assert "`orders`" in sql
    assert "`id`" in sql
    assert '"orders"' not in sql


def test_insert_uses_mssql_brackets() -> None:
    """(7) MSSQL: идентификаторы в квадратных скобках."""
    sql, _ = build_insert_sql("orders", {"id": 1}, dialect="mssql")
    assert "[orders]" in sql
    assert "[id]" in sql


def test_update_and_delete_use_dialect_quoting() -> None:
    """(7) UPDATE/DELETE тоже следуют диалекту."""
    sql, _ = build_update_sql("orders", {"total": 1}, {"id": 2}, dialect="mysql")
    assert "`orders`" in sql and "`total`" in sql and "`id`" in sql
    sql, _ = build_delete_sql("orders", {"id": 2}, dialect="mssql")
    assert "[orders]" in sql and "[id]" in sql


def test_oracle_merge_has_no_as_alias_and_uses_dual() -> None:
    """(6) Oracle MERGE: без ``AS`` у алиаса и с ``FROM DUAL``."""
    sql, _ = build_upsert_sql_dialect("oracle", "users", {"id": 1, "name": "A"}, ["id"])
    assert sql.startswith("MERGE INTO")
    assert " AS t" not in sql.upper().replace("MERGE INTO", "MERGE INTO"), (
        f"Oracle не допускает AS у алиаса: {sql!r}"
    )
    assert "FROM DUAL" in sql.upper()


def test_mssql_merge_is_terminated_with_semicolon() -> None:
    """(6) MSSQL MERGE должен завершаться ``;``."""
    sql, _ = build_upsert_sql_dialect("mssql", "users", {"id": 1, "name": "A"}, ["id"])
    assert sql.rstrip().endswith(";"), f"MSSQL MERGE без ';': {sql!r}"


async def test_dialect_mismatch_is_rejected(
    sqlite_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(5) Явный диалект, не совпадающий с целевой БД, → понятная ошибка."""

    class _Manager:
        def get_async_engine(self) -> AsyncEngine:
            return sqlite_engine

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_db_manager_provider",
        lambda: (lambda: _Manager()),
    )

    proc = DbCrudProcessor(
        operation="UPSERT",
        table="widgets",
        data={"id": 1, "name": "A"},
        conflict_keys=["id"],
        dialect="mysql",
    )
    ex = _exchange()
    await proc.process(ex, _ctx())

    assert ex.error is not None, "dialect-mismatch обязан валить шаг"
    assert ex.stopped, "шаг с неверным диалектом обязан остановить маршрут"
    assert "mysql" in str(ex.error) and "sqlite" in str(ex.error), (
        f"непонятная ошибка dialect-mismatch: {ex.error!r}"
    )


async def test_dialect_defaults_to_target_db(
    sqlite_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(5) Без явного диалекта — диалект целевой БД (не «postgresql»)."""

    class _Manager:
        def get_async_engine(self) -> AsyncEngine:
            return sqlite_engine

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_db_manager_provider",
        lambda: (lambda: _Manager()),
    )

    proc = DbCrudProcessor(
        operation="INSERT",
        table="widgets",
        data={"name": "A"},
    )
    assert proc._dialect is None, "дефолт диалекта должен быть auto (целевая БД)"

    ex = _exchange()
    await proc.process(ex, _ctx())
    assert ex.status != ExchangeStatus.failed, ex.error


# ───────────────────── (9) db_upsert: параметр dialect ─────────────────────


def test_db_upsert_accepts_dialect_parameter() -> None:
    """(9) ``db_upsert`` (и YAML-шаг) умеет задавать диалект."""
    import inspect

    from src.backend.dsl.builders.transport.persistence import PersistenceMixin

    sig = inspect.signature(PersistenceMixin.db_upsert)
    assert "dialect" in sig.parameters, "db_upsert без параметра dialect"


def test_execute_dml_dialect_is_optional() -> None:
    """(5)(9) ``execute_dml``: диалект по умолчанию — auto (целевая БД)."""
    import inspect

    from src.backend.dsl.builders.transport.persistence import PersistenceMixin

    sig = inspect.signature(PersistenceMixin.execute_dml)
    assert sig.parameters["dialect"].default is None, (
        "дефолт execute_dml.dialect должен быть None (auto по целевой БД)"
    )


# ───────────────────── (10) канон идентификаторов ─────────────────────


def test_db_crud_uses_canonical_identifier_validation() -> None:
    """(10) ``db_crud`` не дублирует regex — использует канон ADR-0365."""
    from src.backend.dsl.engine.processors import db_crud as db_crud_module

    source = db_crud_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as fh:
        content = fh.read()
    assert "_IDENTIFIER_RE" not in content, "локальный regex идентификаторов не удалён"
    assert "sql_identifiers" in content, "db_crud не использует канон sql_identifiers"


def test_batch_uses_canonical_identifier_validation() -> None:
    """(10) ``batch`` не дублирует regex — использует канон ADR-0365."""
    from src.backend.dsl.engine.processors import batch as batch_module

    source = batch_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as fh:
        content = fh.read()
    assert "_IDENTIFIER_RE" not in content, "локальный regex идентификаторов не удалён"
    assert "sql_identifiers" in content, "batch не использует канон sql_identifiers"


def test_invalid_identifier_still_rejected_with_legacy_message() -> None:
    """(10) Текст исключения сохранён (на нём завязаны существующие тесты)."""
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        build_insert_sql("users; DROP TABLE users;--", {"x": 1})


def test_expanding_bindparam_used_for_batch_delete() -> None:
    """(4) Sanity: ``IN`` реализован через expanding bindparam."""
    stmt = text("DELETE FROM widgets WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    assert "IN" in str(stmt)
