"""Unit-тесты для модуля snapshot_job (PG → SQLite background sync).

Покрывают:
    - is_snapshot_fresh — проверка порога свежести.
    - sync_pg_to_sqlite — замоканная репликация per-table (DELETE+INSERT).
    - run_snapshot_now — оркестрация, обновление глобального состояния, метрики.
    - Обработка ошибок: логирование + инкремент snapshot_sync_errors_total.
    - Prometheus-метрики: snapshot_rows_total, snapshot_sync_duration_seconds.

Все тесты — без реального PostgreSQL/SQLite (полный mock).
"""

from __future__ import annotations

import time
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
def mock_metrics() -> Any:
    """Замоканный metrics_registry с gauge/counter."""
    with patch(
        "src.backend.infrastructure.observability.metrics_registry.metrics_registry"
    ) as reg:
        age_gauge = MagicMock()
        rows_gauge = MagicMock()
        duration_gauge = MagicMock()
        errors_counter = MagicMock()
        labels_mock = MagicMock()
        reg.gauge.side_effect = [age_gauge, rows_gauge, duration_gauge]
        reg.counter.return_value = errors_counter
        rows_gauge.labels.return_value = labels_mock
        yield {
            "age": age_gauge,
            "rows": rows_gauge,
            "duration": duration_gauge,
            "errors": errors_counter,
            "labels": labels_mock,
        }


@pytest.fixture
def mock_table() -> MagicMock:
    """Mock SQLAlchemy Table с именем и columns."""
    tbl = MagicMock()
    tbl.name = "users"
    tbl.columns = []
    return tbl


@pytest.fixture
def mock_engines(mock_table: MagicMock) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
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


# ──────────────────────────────────────────────────────────────────────────
# is_snapshot_fresh
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_is_snapshot_fresh_no_sync() -> None:
    """Если sync ещё ни разу не выполнялся — всегда False."""
    assert sj.is_snapshot_fresh(threshold_seconds=300) is False
    assert sj.is_snapshot_fresh(threshold_seconds=None) is False


@pytest.mark.unit
def test_is_snapshot_fresh_within_threshold() -> None:
    """age < threshold → True."""
    sj._last_sync_ts = time.time() - 100
    assert sj.is_snapshot_fresh(threshold_seconds=300) is True


@pytest.mark.unit
def test_is_snapshot_fresh_exceeds_threshold() -> None:
    """age > threshold → False."""
    sj._last_sync_ts = time.time() - 400
    assert sj.is_snapshot_fresh(threshold_seconds=300) is False


@pytest.mark.unit
@patch("src.backend.core.config.settings.settings")
def test_is_snapshot_fresh_uses_settings_threshold(mock_settings: MagicMock) -> None:
    """При threshold=None берётся fresh_threshold_seconds из конфигурации."""
    mock_settings.snapshot.fresh_threshold_seconds = 200
    sj._last_sync_ts = time.time() - 150
    assert sj.is_snapshot_fresh(threshold_seconds=None) is True

    sj._last_sync_ts = time.time() - 250
    assert sj.is_snapshot_fresh(threshold_seconds=None) is False


# ──────────────────────────────────────────────────────────────────────────
# sync_pg_to_sqlite
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.infrastructure.database.models.base.metadata")
def test_sync_pg_to_sqlite_success(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
) -> None:
    """Успешная репликация: DELETE + INSERT, возврат rowcount."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, pg_conn, sqlite_engine, sqlite_conn = mock_engines

    select_stmt = MagicMock()
    mock_select.return_value = select_stmt
    delete_stmt = MagicMock()
    mock_delete.return_value = delete_stmt
    insert_stmt = MagicMock()
    mock_insert.return_value = insert_stmt

    result = sj.sync_pg_to_sqlite(pg_engine, sqlite_engine, [mock_table.name])

    assert result == {mock_table.name: 2}
    mock_select.assert_called_once_with(mock_table)
    pg_conn.execute.assert_called_once_with(select_stmt)
    mock_metadata.create_all.assert_called_once_with(
        sqlite_engine, tables=[mock_table], checkfirst=True
    )
    mock_delete.assert_called_once_with(mock_table)
    sqlite_conn.execute.assert_any_call(delete_stmt)
    mock_insert.assert_called_once_with(mock_table)
    sqlite_conn.execute.assert_any_call(
        insert_stmt, [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    )


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.infrastructure.database.models.base.metadata")
def test_sync_pg_to_sqlite_empty_rows(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
) -> None:
    """Если в PG 0 строк — DELETE вызывается, INSERT НЕ вызывается."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, pg_conn, sqlite_engine, sqlite_conn = mock_engines
    pg_conn.execute.return_value.mappings.return_value.all.return_value = []

    select_stmt = MagicMock()
    mock_select.return_value = select_stmt
    delete_stmt = MagicMock()
    mock_delete.return_value = delete_stmt

    result = sj.sync_pg_to_sqlite(pg_engine, sqlite_engine, [mock_table.name])

    assert result == {mock_table.name: 0}
    mock_delete.assert_called_once_with(mock_table)
    sqlite_conn.execute.assert_any_call(delete_stmt)
    mock_insert.assert_not_called()


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.insert")
@patch("src.backend.infrastructure.resilience.snapshot_job.delete")
@patch("src.backend.infrastructure.resilience.snapshot_job.select")
@patch("src.backend.infrastructure.database.models.base.metadata")
def test_sync_pg_to_sqlite_skips_unknown_table(
    mock_metadata: MagicMock,
    mock_select: MagicMock,
    mock_delete: MagicMock,
    mock_insert: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mock_table: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Неизвестные имена таблиц пропускаются с warning, остальные реплицируются."""
    mock_metadata.tables = {mock_table.name: mock_table}
    pg_engine, _, sqlite_engine, _ = mock_engines

    select_stmt = MagicMock()
    mock_select.return_value = select_stmt

    with caplog.at_level("WARNING"):
        result = sj.sync_pg_to_sqlite(
            pg_engine, sqlite_engine, ["unknown_tbl", mock_table.name]
        )

    assert mock_table.name in result
    assert "unknown_tbl" not in result
    assert any("unknown_tbl" in rec.message for rec in caplog.records)
    mock_select.assert_called_once_with(mock_table)


@pytest.mark.unit
@patch("src.backend.infrastructure.database.models.base.metadata")
def test_sync_pg_to_sqlite_no_tables(
    mock_metadata: MagicMock,
    mock_engines: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Пустой список таблиц → warning и пустой dict."""
    mock_metadata.tables = {}
    pg_engine, _, sqlite_engine, _ = mock_engines

    with caplog.at_level("WARNING"):
        result = sj.sync_pg_to_sqlite(pg_engine, sqlite_engine, [])

    assert result == {}
    assert any("пуст" in rec.message.lower() for rec in caplog.records)


# ──────────────────────────────────────────────────────────────────────────
# run_snapshot_now
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.create_engine")
@patch("src.backend.infrastructure.resilience.snapshot_job.sync_pg_to_sqlite")
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_success(
    mock_settings: MagicMock,
    mock_sync: MagicMock,
    mock_create_engine: MagicMock,
    reset_snapshot_state: None,
) -> None:
    """Успешный полный цикл: engines → sync → state → metrics."""
    mock_settings.snapshot = MagicMock(
        enabled=True,
        tables=["users"],
        target_path="var/db/test.sqlite",
        fresh_threshold_seconds=300,
        interval_minutes=10,
    )
    mock_settings.database.sync_connection_url = "postgresql://test"
    mock_sync.return_value = {"users": 5}

    # Фиксируем время для предсказуемости.
    fixed_ts = 1_700_000_000.0
    with patch("time.time", return_value=fixed_ts), patch(
        "time.perf_counter", side_effect=[0.0, 1.23]
    ):
        result = sj.run_snapshot_now()

    assert result == {"users": 5}
    assert sj._last_sync_ts == fixed_ts
    assert sj._last_sync_rows == {"users": 5}
    assert sj._last_sync_duration == pytest.approx(1.23)

    mock_create_engine.assert_any_call("postgresql://test", pool_pre_ping=True)
    mock_sync.assert_called_once()


@pytest.mark.unit
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_disabled(mock_settings: MagicMock) -> None:
    """enabled=False → skip, engines не создаются."""
    mock_settings.snapshot = MagicMock(enabled=False)
    assert sj.run_snapshot_now() == {}


@pytest.mark.unit
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_empty_tables(mock_settings: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """Пустой список tables → skip с warning."""
    mock_settings.snapshot = MagicMock(enabled=True, tables=[])
    assert sj.run_snapshot_now() == {}
    assert any("пуст" in rec.message.lower() for rec in caplog.records)


@pytest.mark.unit
@patch("src.backend.infrastructure.resilience.snapshot_job.create_engine")
@patch("src.backend.infrastructure.resilience.snapshot_job.sync_pg_to_sqlite")
@patch("src.backend.core.config.settings.settings")
def test_run_snapshot_now_error_increments_counter(
    mock_settings: MagicMock,
    mock_sync: MagicMock,
    mock_create_engine: MagicMock,
    reset_snapshot_state: None,
    mock_metrics: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Исключение в sync → лог error, inc() на snapshot_sync_errors_total, проброс."""
    # Инициализируем метрики заранее, чтобы _errors_counter был не None.
    sj._ensure_metrics()
    sj._errors_counter = mock_metrics["errors"]

    mock_settings.snapshot = MagicMock(
        enabled=True,
        tables=["users"],
        target_path="var/db/test.sqlite",
        fresh_threshold_seconds=300,
        interval_minutes=10,
    )
    mock_settings.database.sync_connection_url = "postgresql://test"
    mock_sync.side_effect = RuntimeError("pg connection lost")

    with pytest.raises(RuntimeError, match="pg connection lost"):
        sj.run_snapshot_now()

    mock_metrics["errors"].inc.assert_called_once()
    assert any("sync упал" in rec.message for rec in caplog.records)


# ──────────────────────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ensure_metrics_lazy_init(mock_metrics: Any) -> None:
    """_ensure_metrics лениво создаёт gauge/counter через registry."""
    sj._ensure_metrics()
    assert sj._metrics_initialized is True
    assert sj._age_gauge is mock_metrics["age"]
    assert sj._rows_gauge is mock_metrics["rows"]
    assert sj._duration_gauge is mock_metrics["duration"]
    assert sj._errors_counter is mock_metrics["errors"]


@pytest.mark.unit
def test_publish_metrics_sets_values(mock_metrics: Any) -> None:
    """_publish_metrics прокидывает текущее состояние в Prometheus."""
    sj._ensure_metrics()
    sj._age_gauge = mock_metrics["age"]
    sj._rows_gauge = mock_metrics["rows"]
    sj._duration_gauge = mock_metrics["duration"]

    fixed_ts = time.time() - 60.0
    sj._last_sync_ts = fixed_ts
    sj._last_sync_duration = 2.5
    sj._last_sync_rows = {"users": 42, "orders": 7}

    sj._publish_metrics()

    mock_metrics["age"].set.assert_called_once_with(pytest.approx(60.0, abs=1.0))
    mock_metrics["duration"].set.assert_called_once_with(2.5)
    mock_metrics["rows"].labels.assert_any_call(table="users")
    mock_metrics["rows"].labels.assert_any_call(table="orders")
    mock_metrics["labels"].set.assert_any_call(42)
    mock_metrics["labels"].set.assert_any_call(7)


@pytest.mark.unit
def test_publish_metrics_no_sync_skips(mock_metrics: Any) -> None:
    """Если sync ещё не был — _publish_metrics ничего не трогает."""
    sj._ensure_metrics()
    sj._age_gauge = mock_metrics["age"]
    sj._duration_gauge = mock_metrics["duration"]
    sj._rows_gauge = mock_metrics["rows"]

    sj._publish_metrics()

    mock_metrics["age"].set.assert_not_called()
    mock_metrics["duration"].set.assert_not_called()
    mock_metrics["rows"].labels.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# Scheduler integration
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("src.backend.core.config.settings.settings")
def test_register_snapshot_job_disabled(mock_settings: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """enabled=False → job не регистрируется."""
    mock_settings.snapshot = MagicMock(enabled=False)
    scheduler = MagicMock()
    sj.register_snapshot_job(scheduler)
    scheduler.add_job.assert_not_called()


@pytest.mark.unit
@patch("src.backend.core.config.settings.settings")
def test_register_snapshot_job_enabled(mock_settings: MagicMock) -> None:
    """enabled=True → add_job с корректными параметрами."""
    mock_settings.snapshot = MagicMock(
        enabled=True,
        interval_minutes=5,
        tables=["users", "orders"],
    )
    mock_settings.scheduler.default_jobstore_name = "default"
    scheduler = MagicMock()
    sj.register_snapshot_job(scheduler)

    scheduler.add_job.assert_called_once()
    call_kwargs = scheduler.add_job.call_args.kwargs
    assert call_kwargs["id"] == sj.SNAPSHOT_JOB_ID
    assert call_kwargs["trigger"] == "interval"
    assert call_kwargs["minutes"] == 5
    assert call_kwargs["replace_existing"] is True
    assert call_kwargs["max_instances"] == 1
