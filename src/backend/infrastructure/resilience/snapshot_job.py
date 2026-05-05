"""PG → SQLite snapshot job (Wave 26.8).

Background-задача периодически реплицирует read-only critical таблицы
из PostgreSQL в локальный SQLite-файл, который используется
``ResilienceCoordinator`` как fallback для компонента ``db_main``
(см. ``database_chain.py::_sqlite_ro_query``).

Архитектурные решения (см. ADR-037):

* Полная транзакционная замена per-table: ``BEGIN; DELETE FROM tbl;
  INSERT ...; COMMIT;`` — простая семантика "replace-all", без
  upsert-сложности и FK-конфликтов.
* DDL для SQLite автоматически: ``Base.metadata.create_all`` — структура
  таблиц берётся из тех же ORM-моделей, что и PG.
* Прямое чтение через ``Engine.connect()`` (без ORM) — для скорости и
  чтобы не тащить SQLAlchemy-Continuum / triggers в SQLite-snapshot.
* Регистрация APScheduler-job'а через ``IntervalTrigger`` —
  совместимо с уже существующим ``scheduler_manager``.

Метрики Prometheus:

* ``snapshot_age_seconds`` (Gauge) — секунды с последнего успешного sync.
* ``snapshot_rows_total{table}`` (Gauge) — кол-во строк в snapshot per
  таблице (после последнего sync).
* ``snapshot_sync_duration_seconds`` (Gauge) — длительность последнего sync.
* ``snapshot_sync_errors_total`` (Counter) — суммарное число failed sync.

Health-check: ``is_snapshot_fresh(threshold)`` — для интеграции с
``HealthAggregator``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Table, create_engine, delete, insert, select
from sqlalchemy.engine import Connection

__all__ = (
    "is_snapshot_fresh",
    "register_snapshot_job",
    "run_snapshot_now",
    "sync_pg_to_sqlite",
)

logger = logging.getLogger(__name__)


#: Время последнего успешного sync (monotonic-aware: wall-clock UNIX timestamp).
_last_sync_ts: float | None = None
#: Длительность последнего sync (секунды).
_last_sync_duration: float = 0.0
#: Кол-во строк per таблица после последнего sync.
_last_sync_rows: dict[str, int] = {}


# ──────────────────────────────────────────────────────────────────────
# Prometheus метрики (lazy-init для избежания circular import).
# ──────────────────────────────────────────────────────────────────────
_metrics_initialized = False
_age_gauge: Any = None
_rows_gauge: Any = None
_duration_gauge: Any = None
_errors_counter: Any = None


def _ensure_metrics() -> None:
    """Lazy-init Prometheus-метрик (чтобы не падать при import без зависимости)."""
    global \
        _metrics_initialized, \
        _age_gauge, \
        _rows_gauge, \
        _duration_gauge, \
        _errors_counter
    if _metrics_initialized:
        return
    try:
        from prometheus_client import Counter, Gauge

        _age_gauge = Gauge(
            "snapshot_age_seconds",
            "Seconds since last successful PG → SQLite snapshot sync",
        )
        _rows_gauge = Gauge(
            "snapshot_rows_total",
            "Rows replicated to SQLite snapshot per table",
            labelnames=["table"],
        )
        _duration_gauge = Gauge(
            "snapshot_sync_duration_seconds",
            "Duration of last PG → SQLite snapshot sync",
        )
        _errors_counter = Counter(
            "snapshot_sync_errors_total", "Total failed PG → SQLite snapshot syncs"
        )
        _metrics_initialized = True
    except ImportError:
        # prometheus_client не установлен — пропускаем без шума.
        _metrics_initialized = True


def _publish_metrics() -> None:
    """Публикует актуальное состояние snapshot'а в Prometheus."""
    _ensure_metrics()
    if _last_sync_ts is None:
        return
    if _age_gauge is not None:
        _age_gauge.set(time.time() - _last_sync_ts)
    if _duration_gauge is not None:
        _duration_gauge.set(_last_sync_duration)
    if _rows_gauge is not None:
        for table_name, count in _last_sync_rows.items():
            _rows_gauge.labels(table=table_name).set(count)


# ──────────────────────────────────────────────────────────────────────
# Core sync logic.
# ──────────────────────────────────────────────────────────────────────
def _build_pg_url() -> str:
    """Возвращает sync-DSN для PostgreSQL.

    Для snapshot job'а используется SYNC engine (psycopg2): APScheduler
    запускает job либо в threadpool, либо в asyncio-исполнителе; sync-
    логика проще и не блокирует event loop, если job уйдёт в threadpool.

    ``sync_connection_url`` — pydantic ``@computed_field``; mypy видит его
    как метод-property (Callable[[], str]), поэтому приводим к ``str`` явно.
    """
    from src.core.config.settings import settings

    return str(settings.database.sync_connection_url)


def _build_sqlite_url(target_path: str) -> str:
    """Возвращает SQLAlchemy-URL для SQLite-snapshot файла."""
    snapshot_path = Path(target_path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{snapshot_path}"


def _select_tables(metadata_tables: dict[str, Table], wanted: list[str]) -> list[Table]:
    """Возвращает список ``Table``-объектов в порядке ``wanted``.

    Неизвестные имена логируются и пропускаются (не падаем — лучше
    реплицировать частично, чем не реплицировать вообще).
    """
    result: list[Table] = []
    for name in wanted:
        table = metadata_tables.get(name)
        if table is None:
            logger.warning(
                "Snapshot: таблица '%s' не найдена в metadata — пропускаю", name
            )
            continue
        result.append(table)
    return result


def _replicate_table(pg_conn: Connection, sqlite_conn: Connection, table: Table) -> int:
    """Реплицирует одну таблицу: ``DELETE FROM tbl; INSERT ...``.

    Возвращает кол-во вставленных строк. Использует batch-вставку через
    SQLAlchemy Core для скорости и минимального memory-footprint.
    """
    # Читаем все строки из PG — для read-only critical таблиц это
    # компактные lookup'ы (orderkinds / users / orders), не миллионы строк.
    rows = pg_conn.execute(select(table)).mappings().all()

    # Транзакционная замена.
    sqlite_conn.execute(delete(table))
    if rows:
        sqlite_conn.execute(insert(table), [dict(row) for row in rows])
    return len(rows)


def sync_pg_to_sqlite(
    pg_engine: Engine, sqlite_engine: Engine, tables: list[str]
) -> dict[str, int]:
    """Реплицирует список таблиц из PG в SQLite-snapshot.

    Args:
        pg_engine: SYNC SQLAlchemy engine, указывающий на PostgreSQL.
        sqlite_engine: SYNC SQLAlchemy engine, указывающий на SQLite-файл.
        tables: упорядоченный список имён таблиц (FK-таблицы первыми).

    Returns:
        Словарь ``{table_name: rows_replicated}`` для всех успешно
        реплицированных таблиц.

    Raises:
        Любое исключение SQLAlchemy. Вызывающая сторона (планировщик
        или ``run_snapshot_now``) обязана обработать его и
        инкрементировать ``snapshot_sync_errors_total``.
    """
    # Импорт моделей для side-effect: они регистрируются в metadata.tables.
    # Без этого metadata.create_all вернёт пустую структуру.
    import src.infrastructure.database.models  # noqa: F401  pyright: ignore[reportUnusedImport]
    from src.infrastructure.database.models.base import metadata

    target_tables = _select_tables(metadata.tables, tables)
    if not target_tables:
        logger.warning("Snapshot: список таблиц пуст — нечего реплицировать")
        return {}

    # DDL: создаём только нужные таблицы в SQLite (idempotent).
    metadata.create_all(sqlite_engine, tables=target_tables, checkfirst=True)

    rows_per_table: dict[str, int] = {}

    with pg_engine.connect() as pg_conn, sqlite_engine.begin() as sqlite_conn:
        for table in target_tables:
            count = _replicate_table(pg_conn, sqlite_conn, table)
            rows_per_table[table.name] = count
            logger.info("Snapshot: '%s' реплицирована (%d строк)", table.name, count)

    return rows_per_table


def run_snapshot_now() -> dict[str, int]:
    """Синхронный entry-point для startup hook / manual-trigger.

    Создаёт engine'ы, выполняет sync, обновляет внутреннее состояние и
    публикует метрики. Безопасен к повторным вызовам (idempotent —
    DELETE+INSERT в одной транзакции).
    """
    global _last_sync_ts, _last_sync_duration, _last_sync_rows

    from src.core.config.settings import settings

    snapshot_cfg = settings.snapshot
    if not snapshot_cfg.enabled:
        logger.info("Snapshot: отключён (snapshot.enabled=false), skip")
        return {}

    if not snapshot_cfg.tables:
        logger.warning("Snapshot: список таблиц пуст в base.yml — skip")
        return {}

    pg_engine: Engine | None = None
    sqlite_engine: Engine | None = None
    started = time.perf_counter()
    _ensure_metrics()
    try:
        pg_engine = create_engine(_build_pg_url(), pool_pre_ping=True)
        sqlite_engine = create_engine(_build_sqlite_url(snapshot_cfg.target_path))

        rows = sync_pg_to_sqlite(pg_engine, sqlite_engine, snapshot_cfg.tables)

        _last_sync_ts = time.time()
        _last_sync_duration = time.perf_counter() - started
        _last_sync_rows = rows
        _publish_metrics()

        logger.info(
            "Snapshot: sync завершён за %.2fs, %d таблиц, %d строк всего",
            _last_sync_duration,
            len(rows),
            sum(rows.values()),
        )
        return rows
    except Exception as exc:
        if _errors_counter is not None:
            _errors_counter.inc()
        logger.error(
            "Snapshot: sync упал (%s: %s)", type(exc).__name__, exc, exc_info=True
        )
        raise
    finally:
        if pg_engine is not None:
            pg_engine.dispose()
        if sqlite_engine is not None:
            sqlite_engine.dispose()


# ──────────────────────────────────────────────────────────────────────
# Health-check / freshness.
# ──────────────────────────────────────────────────────────────────────
def is_snapshot_fresh(threshold_seconds: int | None = None) -> bool:
    """Проверяет, что snapshot моложе ``threshold_seconds``.

    Если ``threshold_seconds`` не задан — используется
    ``settings.snapshot.fresh_threshold_seconds``.

    Возвращает ``False`` если sync ещё ни разу не выполнялся.
    """
    if _last_sync_ts is None:
        return False
    if threshold_seconds is None:
        from src.core.config.settings import settings

        threshold_seconds = settings.snapshot.fresh_threshold_seconds
    return (time.time() - _last_sync_ts) < threshold_seconds


def get_snapshot_age_seconds() -> float | None:
    """Возвращает секунды с последнего успешного sync, или ``None``."""
    if _last_sync_ts is None:
        return None
    return time.time() - _last_sync_ts


# ──────────────────────────────────────────────────────────────────────
# Scheduler integration.
# ──────────────────────────────────────────────────────────────────────
SNAPSHOT_JOB_ID = "resilience_snapshot_pg_to_sqlite"


def register_snapshot_job(scheduler: Any) -> None:
    """Регистрирует snapshot job в APScheduler-инстансе.

    Использует ``IntervalTrigger`` (cron-like период
    ``snapshot.interval_minutes``). Job выполняется в threadpool-
    executor'е (sync-логика); в SQLAlchemyJobStore сохраняется по
    ``SNAPSHOT_JOB_ID`` для idempotent-перезапуска.

    Если ``snapshot.enabled=false`` — job НЕ регистрируется.
    """
    from src.core.config.settings import settings

    snapshot_cfg = settings.snapshot
    if not snapshot_cfg.enabled:
        logger.info("Snapshot: job не регистрируется (snapshot.enabled=false)")
        return

    scheduler.add_job(
        func=run_snapshot_now,
        trigger="interval",
        minutes=snapshot_cfg.interval_minutes,
        id=SNAPSHOT_JOB_ID,
        name="PG → SQLite snapshot sync (W26.8)",
        replace_existing=True,
        jobstore=settings.scheduler.default_jobstore_name,
        executor="default",  # threadpool — sync-логика.
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Snapshot: job '%s' зарегистрирован (interval=%d min, %d таблиц)",
        SNAPSHOT_JOB_ID,
        snapshot_cfg.interval_minutes,
        len(snapshot_cfg.tables),
    )
