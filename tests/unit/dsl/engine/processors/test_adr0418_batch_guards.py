"""ADR-0418 — гварды batch-процессоров (capability / quoting / tenant / лимит).

Дефект волны 24 (кластер F3, medium): ``batch_insert`` / ``batch_update`` /
``batch_delete`` шли в БД без единого защитного контура:

* **нет capability-гейта** — шаг писал в любую внешнюю БД (в отличие от
  ``db_crud`` / ``db_query``, где ``required_capability`` объявлен);
* **идентификаторы не квотятся** — ``f"INSERT INTO {self._table} ..."``
  (зарезервированное слово → синтаксическая ошибка, диалект не учтён);
* **нет tenant-скоупа** — запись в tenant-таблицу шла без tenant-предиката;
* **нет лимита размера батча** — один шаг мог залить миллионы строк;
* **дефолт ``profile="default"`` не существует** → ``DatabaseError`` на
  каждом шаге.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.batch import (
    AUTO_PROFILE,
    MAX_BATCH_ROWS,
    BatchDeleteProcessor,
    BatchInsertProcessor,
    BatchUpdateProcessor,
)

pytestmark = pytest.mark.unit


def _ex(body: Any = None) -> Exchange[Any]:
    """Exchange с заданным телом."""
    return Exchange(in_message=Message(body=body, headers={}))


class _Recorder:
    """Заглушка bundle/session: пишет исполненный SQL и параметры."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.params: list[Any] = []

    def bundle(self) -> MagicMock:
        """Собрать bundle с записывающей сессией."""
        recorder = self

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=lambda stmt, params=None: recorder._record(stmt, params)
        )
        session.commit = AsyncMock()

        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=session)
        context_manager.__aexit__ = AsyncMock(return_value=False)

        bundle = MagicMock()
        bundle.async_session_maker.return_value = context_manager
        # Внешняя БД без tenant-aware схемы — диалект PostgreSQL по умолчанию.
        bundle.settings.type.value = "postgresql"
        return bundle

    def _record(self, stmt: Any, params: Any) -> MagicMock:
        """Записать SQL и параметры."""
        self.statements.append(str(stmt))
        self.params.append(params)
        result = MagicMock()
        result.rowcount = 1
        return result


@pytest.fixture
def recorder() -> _Recorder:
    """Заглушка внешней БД с записью SQL."""
    return _Recorder()


@pytest.fixture
def external_registry(recorder: _Recorder) -> Any:
    """Подмена реестра внешних БД (профиль ``probe``)."""
    registry = MagicMock()
    registry.get_bundle.return_value = recorder.bundle()
    with patch(
        "src.backend.dsl.engine.processors.batch._lazy_get_external_db_registry",
        lambda: lambda: registry,
    ):
        yield registry


# ── capability-гейт ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "processor_cls", [BatchInsertProcessor, BatchUpdateProcessor, BatchDeleteProcessor]
)
def test_batch_processors_require_db_write(processor_cls: type[Any]) -> None:
    """Все batch-процессоры объявляют ``db.write`` (ADR-0393-канон)."""
    assert processor_cls.required_capability == "db.write"


async def test_batch_insert_denied_capability_does_not_touch_db(
    external_registry: Any,
) -> None:
    """Отказ capability-гейта — шаг не ходит в БД."""
    from src.backend.dsl.engine.processors.base import BaseProcessor

    async def _deny(self: Any, exchange: Any, **kwargs: Any) -> bool:
        exchange.fail("denied")
        exchange.stop()
        return False

    with patch.object(BaseProcessor, "auth_check", _deny):
        proc = BatchInsertProcessor(table="orders", items=[{"id": 1}], profile="probe")
        exchange = _ex()
        await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.stopped
    external_registry.get_bundle.assert_not_called()


async def test_batch_insert_calls_auth_check(external_registry: Any) -> None:
    """Capability-гейт вызывается до обращения к БД."""
    from src.backend.dsl.engine.processors.base import BaseProcessor

    calls: list[str] = []

    async def _allow(
        self: Any, exchange: Any, *, action: str = "execute", **kw: Any
    ) -> bool:
        calls.append(action)
        return True

    with patch.object(BaseProcessor, "auth_check", _allow):
        proc = BatchInsertProcessor(table="orders", items=[{"id": 1}], profile="probe")
        await proc.process(_ex(), None)  # type: ignore[arg-type]

    assert calls == ["write"]


# ── квотирование идентификаторов ──────────────────────────────────────────


async def test_batch_insert_quotes_identifiers(
    external_registry: Any, recorder: _Recorder
) -> None:
    """INSERT квотит таблицу и колонки."""
    proc = BatchInsertProcessor(
        table="orders", items=[{"id": 1, "status": "ok"}], profile="probe"
    )
    await proc.process(_ex(), None)  # type: ignore[arg-type]

    sql = recorder.statements[0]
    assert 'INSERT INTO "orders"' in sql
    assert '"id"' in sql
    assert '"status"' in sql


async def test_batch_update_quotes_identifiers(
    external_registry: Any, recorder: _Recorder
) -> None:
    """UPDATE квотит таблицу, SET-колонки и ключ."""
    proc = BatchUpdateProcessor(
        table="orders", items=[{"id": 1, "status": "ok"}], profile="probe"
    )
    await proc.process(_ex(), None)  # type: ignore[arg-type]

    sql = recorder.statements[0]
    assert 'UPDATE "orders"' in sql
    assert '"status" = :status' in sql
    assert '"id" = :_key' in sql


async def test_batch_delete_quotes_identifiers(
    external_registry: Any, recorder: _Recorder
) -> None:
    """DELETE квотит таблицу и ключевое поле."""
    proc = BatchDeleteProcessor(table="orders", ids=[1, 2], profile="probe")
    await proc.process(_ex(), None)  # type: ignore[arg-type]

    sql = recorder.statements[0]
    assert 'DELETE FROM "orders"' in sql
    assert '"id" IN' in sql


# ── лимит размера батча ───────────────────────────────────────────────────


async def test_batch_insert_rejects_oversized_batch(external_registry: Any) -> None:
    """Батч больше ``max_batch`` — понятная ошибка."""
    proc = BatchInsertProcessor(
        table="orders",
        items=[{"id": 1}, {"id": 2}, {"id": 3}],
        profile="probe",
        max_batch=2,
    )
    exchange = _ex()
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "превышает лимит 2" in exchange.error


async def test_batch_delete_rejects_oversized_batch(external_registry: Any) -> None:
    """Лимит батча применяется и к DELETE."""
    proc = BatchDeleteProcessor(
        table="orders", ids=[1, 2, 3], profile="probe", max_batch=2
    )
    exchange = _ex()
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "превышает лимит 2" in exchange.error


def test_default_max_batch_is_positive() -> None:
    """Лимит батча по умолчанию задан и положителен."""
    assert MAX_BATCH_ROWS > 0


# ── tenant-скоуп ──────────────────────────────────────────────────────────


async def test_batch_insert_requires_tenant_context(external_registry: Any) -> None:
    """Без tenant-контекста шаг с tenant-скоупом падает fail-closed."""
    proc = BatchInsertProcessor(
        table="orders", items=[{"id": 1}], profile="probe", tenant_column="tenant_id"
    )
    exchange = _ex()
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "tenant" in exchange.error.lower()


async def test_batch_insert_scopes_tenant(
    external_registry: Any, recorder: _Recorder
) -> None:
    """INSERT проставляет tenant в данные."""
    from src.backend.core.tenancy import TenantContext, bind_tenant, unbind_tenant

    token = bind_tenant(TenantContext(tenant_id="tenant-a"))
    try:
        proc = BatchInsertProcessor(
            table="orders",
            items=[{"id": 1}],
            profile="probe",
            tenant_column="tenant_id",
        )
        await proc.process(_ex(), None)  # type: ignore[arg-type]
    finally:
        unbind_tenant(token)

    sql = recorder.statements[0]
    assert '"tenant_id"' in sql
    assert recorder.params[0][0]["tenant_id"] == "tenant-a"


async def test_batch_update_scopes_tenant(
    external_registry: Any, recorder: _Recorder
) -> None:
    """UPDATE получает tenant-предикат."""
    from src.backend.core.tenancy import TenantContext, bind_tenant, unbind_tenant

    token = bind_tenant(TenantContext(tenant_id="tenant-a"))
    try:
        proc = BatchUpdateProcessor(
            table="orders",
            items=[{"id": 1, "status": "ok"}],
            profile="probe",
            tenant_column="tenant_id",
        )
        await proc.process(_ex(), None)  # type: ignore[arg-type]
    finally:
        unbind_tenant(token)

    sql = recorder.statements[0]
    assert '"tenant_id" = :_tenant_id' in sql
    assert recorder.params[0][0]["_tenant_id"] == "tenant-a"


async def test_batch_delete_scopes_tenant(
    external_registry: Any, recorder: _Recorder
) -> None:
    """DELETE получает tenant-предикат."""
    from src.backend.core.tenancy import TenantContext, bind_tenant, unbind_tenant

    token = bind_tenant(TenantContext(tenant_id="tenant-a"))
    try:
        proc = BatchDeleteProcessor(
            table="orders", ids=[1], profile="probe", tenant_column="tenant_id"
        )
        await proc.process(_ex(), None)  # type: ignore[arg-type]
    finally:
        unbind_tenant(token)

    sql = recorder.statements[0]
    assert '"tenant_id" = :_tenant_id' in sql
    assert recorder.params[0]["_tenant_id"] == "tenant-a"


async def test_batch_insert_rejects_foreign_tenant(external_registry: Any) -> None:
    """Данные чужого tenant'а — отказ."""
    from src.backend.core.tenancy import TenantContext, bind_tenant, unbind_tenant

    token = bind_tenant(TenantContext(tenant_id="tenant-a"))
    try:
        proc = BatchInsertProcessor(
            table="orders",
            items=[{"id": 1, "tenant_id": "tenant-b"}],
            profile="probe",
            tenant_column="tenant_id",
        )
        exchange = _ex()
        await proc.process(exchange, None)  # type: ignore[arg-type]
    finally:
        unbind_tenant(token)

    assert exchange.error is not None
    assert "чужой tenant" in exchange.error


# ── профиль по умолчанию ──────────────────────────────────────────────────


def test_default_profile_targets_main_database() -> None:
    """``profile="default"`` → основная БД приложения (она есть всегда)."""
    from src.backend.dsl.engine.processors.batch import _resolve_bundle

    bundle = MagicMock()
    with patch(
        "src.backend.core.di.providers.db.get_db_initializer_provider", lambda: bundle
    ):
        resolved = _resolve_bundle(AUTO_PROFILE)

    assert resolved is bundle.as_bundle.return_value


async def test_default_profile_batch_insert_does_not_fail_on_profile(
    external_registry: Any,
) -> None:
    """Явный профиль ведёт во внешнюю БД реестра."""
    proc = BatchInsertProcessor(table="orders", items=[{"id": 1}], profile="probe")
    exchange = _ex()
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is None
    external_registry.get_bundle.assert_called_once_with("probe")
