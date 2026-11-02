"""Unit-тесты режимов межtenant-снапшота (ADR-0413).

Покрывают:

    - ``single-tenant`` (текущее поведение, ADR-0409) — регрессия;
    - ``per-tenant`` — перебор ЯВНОГО списка tenant_id с per-tenant
      ``SET app.tenant_id`` (безопасная альтернатива ``BYPASSRLS``);
    - ``service-role`` — чтение служебной ролью с ``BYPASSRLS`` + проверка
      наличия ``BYPASSRLS`` у роли;
    - fail-closed: пустой список tenant'ов, отсутствие service-DSN,
      неизвестный режим, отсутствие ``BYPASSRLS``, пустой результат —
      ни в одном случае не пишется «тихий» 0-строчный снимок.

Все тесты — без реального PostgreSQL/SQLite (полный mock).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.resilience import snapshot_job as sj

# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_snapshot_state() -> None:
    """Сбрасывает глобальное состояние snapshot_job перед каждым тестом."""
    sj._last_sync_ts = None
    sj._last_sync_duration = 0.0
    sj._last_sync_rows = {}
    sj._metrics_initialized = False
    sj._age_gauge = None
    sj._rows_gauge = None
    sj._duration_gauge = None
    sj._errors_counter = None


@pytest.fixture
def mock_table() -> MagicMock:
    """Mock SQLAlchemy Table с именем и columns."""
    tbl = MagicMock()
    tbl.name = "users"
    tbl.columns = []
    return tbl


@pytest.fixture
def mock_engines(
    mock_table: MagicMock,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Возвращает (pg_engine, pg_conn, sqlite_engine, sqlite_conn)."""
    pg_conn = MagicMock()
    pg_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]

    pg_engine = MagicMock()
    pg_engine.connect.return_value.__enter__ = MagicMock(return_value=pg_conn)
    pg_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    sqlite_conn = MagicMock()
    sqlite_engine = MagicMock()
    sqlite_engine.begin.return_value.__enter__ = MagicMock(return_value=sqlite_conn)
    sqlite_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

    return pg_engine, pg_conn, sqlite_engine, sqlite_conn


def _scope_calls(pg_conn: MagicMock) -> list[dict[str, Any]]:
    """Возвращает параметры всех вызовов ``set_config('app.tenant_id', ...)``."""
    calls: list[dict[str, Any]] = []
    for call in pg_conn.execute.call_args_list:
        sql = str(call.args[0]) if call.args else ""
        if "app.tenant_id" in sql:
            calls.append(call.args[1] if len(call.args) > 1 else {})
    return calls


def _snapshot_settings_mock(**overrides: Any) -> MagicMock:
    """Собирает mock ``settings.snapshot`` с дефолтами тестов."""
    base: dict[str, Any] = {
        "enabled": True,
        "mode": "single-tenant",
        "tables": ["users"],
        "tenants": [],
        "service_dsn": None,
        "target_path": "var/db/test.sqlite",
        "fresh_threshold_seconds": 300,
        "interval_minutes": 10,
    }
    base.update(overrides)
    return MagicMock(**base)


# ──────────────────────────────────────────────────────────────────────────
# Конфигурация: единый источник истины для режимов
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_snapshot_mode_literal_matches_job_constants() -> None:
    """Значения режимов в конфиг-модели и в job'е совпадают.

    Конфигурация (``core.config.services.snapshot``) — источник истины
    для оператора; job не должен разъезжаться с ней (иначе режим из
    YAML молча не узнаётся).
    """
    from typing import get_args

    from src.backend.core.config.services.snapshot import (
        SNAPSHOT_MODE_PER_TENANT,
        SNAPSHOT_MODE_SERVICE_ROLE,
        SNAPSHOT_MODE_SINGLE_TENANT,
        SnapshotMode,
    )

    assert set(get_args(SnapshotMode)) == {
        SNAPSHOT_MODE_SINGLE_TENANT,
        SNAPSHOT_MODE_PER_TENANT,
        SNAPSHOT_MODE_SERVICE_ROLE,
    }
    assert sj._MODE_SINGLE_TENANT == SNAPSHOT_MODE_SINGLE_TENANT
    assert sj._MODE_PER_TENANT == SNAPSHOT_MODE_PER_TENANT
    assert sj._MODE_SERVICE_ROLE == SNAPSHOT_MODE_SERVICE_ROLE


@pytest.mark.unit
def test_snapshot_settings_default_mode_is_single_tenant() -> None:
    """По умолчанию включён текущий single-tenant режим (ADR-0409)."""
    from src.backend.core.config.services.snapshot import SnapshotSettings

    settings_obj = SnapshotSettings()
    assert settings_obj.mode == "single-tenant"
    assert settings_obj.tenants == []
    assert settings_obj.service_dsn is None


@pytest.mark.unit
def test_snapshot_settings_rejects_unknown_mode() -> None:
    """Неизвестный режим отвергается валидатором (fail-closed на старте)."""
    from pydantic import ValidationError

    from src.backend.core.config.services.snapshot import SnapshotSettings

    with pytest.raises(ValidationError):
        SnapshotSettings(mode="per_tenant")


# ──────────────────────────────────────────────────────────────────────────
# run_snapshot_now: маршрутизация по режимам
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.create_engine")
@patch("src.backend.infrastructure.resilience.snapshot_job.sync_pg_to_sqlite")
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_single_tenant_keeps_current_behaviour(
    mock_settings: MagicMock, mock_sync: MagicMock, mock_create_engine: MagicMock
) -> None:
    """Режим single-tenant (по умолчанию) — прежнее поведение не изменилось."""
    mock_settings.snapshot = _snapshot_settings_mock()
    mock_settings.database.sync_connection_url = "postgresql://app"
    mock_sync.return_value = {"users": 3}

    sj.run_snapshot_now(tenant_id="acme")

    mock_sync.assert_called_once()
    assert mock_sync.call_args.kwargs["tenant_id"] == "acme"
    mock_create_engine.assert_any_call("postgresql://app", pool_pre_ping=True)


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.create_engine")
@patch(
    "src.backend.infrastructure.resilience.snapshot_job.sync_multi_tenant_pg_to_sqlite"
)
@patch("src.backend.infrastructure.resilience.snapshot_job.sync_pg_to_sqlite")
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_per_tenant_uses_configured_tenants(
    mock_settings: MagicMock,
    mock_sync_single: MagicMock,
    mock_sync_multi: MagicMock,
    mock_create_engine: MagicMock,
) -> None:
    """Режим per-tenant — перебор явного списка из конфигурации."""
    mock_settings.snapshot = _snapshot_settings_mock(
        mode="per-tenant", tenants=["acme", "globex"]
    )
    mock_settings.database.sync_connection_url = "postgresql://app"
    mock_sync_multi.return_value = {"users": 7}

    result = sj.run_snapshot_now()

    assert result == {"users": 7}
    mock_sync_single.assert_not_called()
    assert mock_sync_multi.call_args.kwargs["tenant_ids"] == ["acme", "globex"]
    # PG-подключение — обычное (app-пользователь), RLS не обходится.
    mock_create_engine.assert_any_call("postgresql://app", pool_pre_ping=True)


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.create_engine")
@patch(
    "src.backend.infrastructure.resilience.snapshot_job.sync_multi_tenant_pg_to_sqlite"
)
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_per_tenant_without_list_fails_closed(
    mock_settings: MagicMock, mock_sync_multi: MagicMock, mock_create_engine: MagicMock
) -> None:
    """per-tenant без явного списка tenant'ов — fail-closed (файл не тронут)."""
    mock_settings.snapshot = _snapshot_settings_mock(mode="per-tenant", tenants=[])
    mock_settings.database.sync_connection_url = "postgresql://app"

    with pytest.raises(sj.SnapshotModeError) as exc_info:
        sj.run_snapshot_now()

    assert "tenant" in str(exc_info.value).lower()
    mock_sync_multi.assert_not_called()
    # Ни одного SQLite-движка: файл snapshot'а остался нетронутым.
    assert all(
        call.args and call.args[0] != "sqlite+pysqlite:///var/db/test.sqlite"
        for call in mock_create_engine.call_args_list
    )


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.create_engine")
@patch(
    "src.backend.infrastructure.resilience.snapshot_job.sync_service_role_pg_to_sqlite"
)
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_service_role_requires_explicit_dsn(
    mock_settings: MagicMock,
    mock_sync_service: MagicMock,
    mock_create_engine: MagicMock,
) -> None:
    """service-role без явного DSN — fail-closed (файл не тронут)."""
    mock_settings.snapshot = _snapshot_settings_mock(mode="service-role")
    mock_settings.database.sync_connection_url = "postgresql://app"

    with pytest.raises(sj.SnapshotModeError) as exc_info:
        sj.run_snapshot_now()

    assert "dsn" in str(exc_info.value).lower()
    mock_sync_service.assert_not_called()
    assert all(
        call.args and call.args[0] != "sqlite+pysqlite:///var/db/test.sqlite"
        for call in mock_create_engine.call_args_list
    )


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.create_engine")
@patch(
    "src.backend.infrastructure.resilience.snapshot_job.sync_service_role_pg_to_sqlite"
)
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_service_role_uses_service_dsn(
    mock_settings: MagicMock,
    mock_sync_service: MagicMock,
    mock_create_engine: MagicMock,
) -> None:
    """service-role — PG-подключение идёт по служебному DSN (с BYPASSRLS)."""
    service_dsn = "postgresql+psycopg://snapshot_service:pwd@pg:5432/app"
    mock_settings.snapshot = _snapshot_settings_mock(
        mode="service-role", service_dsn=MagicMock(get_secret_value=lambda: service_dsn)
    )
    mock_settings.database.sync_connection_url = "postgresql://app"
    mock_sync_service.return_value = {"users": 11}

    result = sj.run_snapshot_now()

    assert result == {"users": 11}
    mock_create_engine.assert_any_call(service_dsn, pool_pre_ping=True)
    # Обычный app-DSN в этом режиме НЕ используется.
    assert all(
        call.args[0] != "postgresql://app"
        for call in mock_create_engine.call_args_list
        if call.args
    )


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.create_engine")
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_unknown_mode_fails_closed(
    mock_settings: MagicMock, mock_create_engine: MagicMock
) -> None:
    """Неизвестный режим — fail-closed до создания движков."""
    mock_settings.snapshot = _snapshot_settings_mock(mode="bogus")
    mock_settings.database.sync_connection_url = "postgresql://app"

    with pytest.raises(sj.SnapshotModeError):
        sj.run_snapshot_now()

    mock_create_engine.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# per-tenant: per-tenant SET на каждый tenant
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.core.domain.models.base.metadata")
def test_sync_multi_tenant_sets_scope_for_every_tenant(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
) -> None:
    """Для каждого tenant'а из явного списка — свой ``SET app.tenant_id``."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, pg_conn, sqlite_engine, _ = mock_engines

    result = sj.sync_multi_tenant_pg_to_sqlite(
        pg_engine, sqlite_engine, [mock_table.name], tenant_ids=["acme", "globex"]
    )

    scopes = _scope_calls(pg_conn)
    assert [call["tenant_id"] for call in scopes] == ["acme", "globex"]
    # Строки обоих tenant'ов попадают в один снимок (сумма 2+2).
    assert result == {mock_table.name: 4}


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.core.domain.models.base.metadata")
def test_sync_multi_tenant_empty_list_fails_closed(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
) -> None:
    """Пустой список tenant'ов — ошибка, а не «пустой» снимок."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, _, sqlite_engine, sqlite_conn = mock_engines

    with pytest.raises(sj.SnapshotModeError):
        sj.sync_multi_tenant_pg_to_sqlite(
            pg_engine, sqlite_engine, [mock_table.name], tenant_ids=[]
        )

    mock_delete.assert_not_called()
    mock_insert.assert_not_called()
    sqlite_conn.execute.assert_not_called()


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.core.domain.models.base.metadata")
def test_sync_multi_tenant_empty_result_fails_closed(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
) -> None:
    """0 строк по всем tenant'ам — ошибка; файл снимка не затирается."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, pg_conn, sqlite_engine, sqlite_conn = mock_engines
    pg_conn.execute.return_value.mappings.return_value.all.return_value = []

    with pytest.raises(sj.SnapshotModeError):
        sj.sync_multi_tenant_pg_to_sqlite(
            pg_engine, sqlite_engine, [mock_table.name], tenant_ids=["acme"]
        )

    mock_delete.assert_not_called()
    mock_insert.assert_not_called()
    sqlite_conn.execute.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# service-role: проверка BYPASSRLS + fail-closed
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.core.domain.models.base.metadata")
def test_sync_service_role_checks_bypassrls_before_select(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
) -> None:
    """Наличие BYPASSRLS проверяется ДО выборки (иначе — тихие 0 строк)."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, pg_conn, sqlite_engine, _ = mock_engines
    select_stmt = MagicMock()
    mock_select.return_value = select_stmt

    result = sj.sync_service_role_pg_to_sqlite(
        pg_engine, sqlite_engine, [mock_table.name]
    )

    assert result == {mock_table.name: 2}
    calls = pg_conn.execute.call_args_list
    bypass_positions = [
        index
        for index, call in enumerate(calls)
        if call.args and "rolbypassrls" in str(call.args[0])
    ]
    select_positions = [
        index
        for index, call in enumerate(calls)
        if call.args and call.args[0] is select_stmt
    ]
    assert bypass_positions, "BYPASSRLS не проверяется"
    assert select_positions
    assert bypass_positions[0] < select_positions[0]
    # Tenant-скоуп не выставляется — чтение идёт под BYPASSRLS.
    assert _scope_calls(pg_conn) == []


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.core.domain.models.base.metadata")
def test_sync_service_role_without_bypassrls_fails_closed(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
) -> None:
    """Роль без BYPASSRLS — ошибка до выборки (а не тихие 0 строк)."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, pg_conn, sqlite_engine, sqlite_conn = mock_engines
    pg_conn.execute.return_value.scalar.return_value = False

    with pytest.raises(sj.SnapshotModeError) as exc_info:
        sj.sync_service_role_pg_to_sqlite(pg_engine, sqlite_engine, [mock_table.name])

    assert "bypassrls" in str(exc_info.value).lower()
    mock_select.assert_not_called()
    mock_delete.assert_not_called()
    mock_insert.assert_not_called()
    sqlite_conn.execute.assert_not_called()


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.core.domain.models.base.metadata")
def test_sync_service_role_empty_result_fails_closed(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
) -> None:
    """Пустой снимок служебной роли — ошибка; файл не затирается."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, pg_conn, sqlite_engine, sqlite_conn = mock_engines
    pg_conn.execute.return_value.mappings.return_value.all.return_value = []

    with pytest.raises(sj.SnapshotModeError):
        sj.sync_service_role_pg_to_sqlite(pg_engine, sqlite_engine, [mock_table.name])

    mock_delete.assert_not_called()
    mock_insert.assert_not_called()
    sqlite_conn.execute.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# Scheduler integration
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("src.backend.core.config.settings.settings")
def test_register_snapshot_job_per_tenant_has_no_tenant_kwarg(
    mock_settings: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """В режиме per-tenant job не ждёт tenant-скоуп из аргумента."""
    mock_settings.snapshot = _snapshot_settings_mock(
        mode="per-tenant", tenants=["acme"], interval_minutes=5
    )
    mock_settings.scheduler.default_jobstore_name = "default"
    scheduler = MagicMock()

    with caplog.at_level("WARNING"):
        sj.register_snapshot_job(scheduler)

    call_kwargs = scheduler.add_job.call_args.kwargs
    assert "tenant_id" not in call_kwargs["kwargs"]
    assert not any("fail-closed" in rec.message for rec in caplog.records)
