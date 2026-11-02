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

Tenant-скоуп (ADR-0400, ADR-0409)
---------------------------------
Таблицы ``users`` / ``orders`` / ``orderkinds`` защищены PostgreSQL-RLS
(политика ``tenant_id = current_setting('app.tenant_id', true)``).
Чтение без выставленного ``app.tenant_id`` возвращает **0 строк** —
снапшот молча пустой (тихая потеря fallback'а ``db_main``). Поэтому перед
выборкой соединение получает явный tenant-скоуп
(:func:`_apply_tenant_scope`): ``set_config('app.tenant_id', ..., true)``
— transaction-local, значение не «залипает» в пуле.

Контракт скоупа (ADR-0409)
--------------------------
**Снапшот покрывает ровно один tenant.** Межtenant-режима нет:

* tenant-скоуп определяется как ``явный аргумент → tenant-контекст
  процесса`` (:func:`_resolve_snapshot_tenant`);
* если скоупа нет — job падает с :class:`SnapshotTenantScopeError`
  (fail-closed), а **не** пишет «пустой» снимок в системном tenant'е:
  под RLS это дало бы 0 строк без ошибки (тихая потеря fallback'а);
* SQLite-файл при отказе не трогается — предыдущий (непустой) снимок
  остаётся валидным.

Режимы межtenant-снапшота (ADR-0413)
-----------------------------------
ADR-0409 зафиксировал контракт «снапшот в пределах одного ``tenant_id``;
без скоупа — fail-closed»: реестра tenant'ов нет, а ``SELECT DISTINCT
tenant_id`` под RLS видит только текущего tenant'а. ADR-0413 добавляет
явно настраиваемый режим (``snapshot.mode``):

* ``single-tenant`` (по умолчанию) — текущее поведение: скоуп из явного
  аргумента → tenant-контекста процесса; без скоупа — fail-closed;
* ``per-tenant`` — **безопасная** альтернатива ``BYPASSRLS``: явный
  список ``snapshot.tenants`` перебирается, для каждого tenant'а
  выставляется свой ``app.tenant_id``; пустой список — fail-closed;
* ``service-role`` — служебный DSN ``snapshot.service_dsn`` пользователя
  с ``BYPASSRLS`` (ADR-0393): чтение всех tenant'ов одним соединением;
  DSN не задан — fail-closed; наличие ``BYPASSRLS`` у роли проверяется
  **до** выборки (:func:`_assert_bypassrls`), иначе снимок был бы тихо
  пустым.

Во всех режимах «тихих 0 строк» нет: пустой результат в режимах
``per-tenant`` / ``service-role`` — ошибка (снимок не пишется, предыдущий
валидный снимок сохраняется), в ``single-tenant`` — WARNING (ADR-0409).

Процедура выдачи служебной роли и риски — ``docs/ops/snapshot-bypassrls-role.md``.

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

import importlib
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Table, create_engine, delete, insert, select, text
from sqlalchemy.engine import Connection

from src.backend.core.logging import get_logger

__all__ = (
    "SnapshotJob",
    "SnapshotModeError",
    "SnapshotTenantScopeError",
    "get_snapshot_job",
    "is_snapshot_fresh",
    "register_snapshot_job",
    "run_snapshot_now",
    "sync_multi_tenant_pg_to_sqlite",
    "sync_pg_to_sqlite",
    "sync_service_role_pg_to_sqlite",
)

logger = get_logger(__name__)


class SnapshotTenantScopeError(RuntimeError):
    """Snapshot запущен без tenant-скоупа (fail-closed, ADR-0409).

    Снапшот покрывает ровно один tenant: под PostgreSQL-RLS выборка без
    ``app.tenant_id`` возвращает 0 строк (тихий пустой fallback). Поэтому
    отсутствие tenant-скоупа — ошибка, а не «снимок в системном tenant'е».
    """


class SnapshotModeError(RuntimeError):
    """Режим межtenant-снапшота сконфигурирован некорректно (ADR-0413).

    Поднимается, когда заявленный режим нельзя выполнить без явного
    решения оператора: пустой список tenant'ов (``per-tenant``),
    отсутствие service-DSN (``service-role``), неизвестное значение
    режима, отсутствие ``BYPASSRLS`` у служебной роли.

    Fail-closed: снимок при этом НЕ пишется — предыдущий (непустой)
    снимок остаётся валидным, fallback ``db_main`` не получает пустых
    данных.
    """


#: Время последнего успешного sync (monotonic-aware: wall-clock UNIX timestamp).
_last_sync_ts: float | None = None
#: Длительность последнего sync (секунды).
_last_sync_duration: float = 0.0
#: Кол-во строк per таблица после последнего sync.
_last_sync_rows: dict[str, int] = {}

#: SQL установки tenant-скоупа для RLS-политик PostgreSQL (ADR-0400).
#:
#: ``set_config(..., true)`` — transaction-local: значение действует до
#: конца транзакции соединения и не «залипает» в пуле. Канон тот же, что
#: в ``core/tenancy/sqlalchemy_filter.py``.
_TENANT_SCOPE_SQL = "SELECT set_config('app.tenant_id', :tenant_id, true)"

#: SQL проверки наличия ``BYPASSRLS`` у роли соединения (ADR-0413).
#:
#: Проверяется сама роль соединения (``rolname = current_user``) и все
#: роли, в которые она входит (``.oid`` через ``pg_has_role``) —
#: атрибут ``BYPASSRLS`` наследуется участниками роли. Без этой проверки
#: служебный DSN без ``BYPASSRLS`` вернул бы 0 строк без ошибки (тихий
#: пустой снимок).
_BYPASSRLS_CHECK_SQL = (
    "SELECT COALESCE(bool_or(r.rolbypassrls), false) "
    "FROM pg_roles r "
    "WHERE r.rolname = current_user "
    "OR pg_has_role(current_user, r.oid, 'MEMBER')"
)

#: Служебный режим чтения (без tenant-скоупа) — только для роли с BYPASSRLS.
_SCOPE_SERVICE_ROLE = "service-role"

#: Обычный режим чтения: tenant-скоуп выставляется на соединение.
_SCOPE_TENANT = "tenant"

#: Режимы межtenant-снапшота (ADR-0413). Значения совпадают с
#: ``core.config.services.snapshot`` (единство источников истины
#: проверяется тестом ``tests/unit/infrastructure/resilience/
#: test_snapshot_job_modes.py``).
_MODE_SINGLE_TENANT = "single-tenant"
_MODE_PER_TENANT = "per-tenant"
_MODE_SERVICE_ROLE = "service-role"


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
        from src.backend.core.utils.metrics_registry import metrics_registry

        _age_gauge = metrics_registry.gauge(
            "snapshot_age_seconds",
            "Seconds since last successful PG → SQLite snapshot sync",
        )
        _rows_gauge = metrics_registry.gauge(
            "snapshot_rows_total",
            "Rows replicated to SQLite snapshot per table",
            labels=("table",),
        )
        _duration_gauge = metrics_registry.gauge(
            "snapshot_sync_duration_seconds",
            "Duration of last PG → SQLite snapshot sync",
        )
        _errors_counter = metrics_registry.counter(
            "snapshot_sync_errors_total", "Total failed PG → SQLite snapshot syncs"
        )
        _metrics_initialized = True
    except ImportError:
        # MetricsRegistry/prometheus_client не установлены — пропускаем без шума.
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

    Для snapshot job'а используется SYNC engine (psycopg): APScheduler
    запускает job либо в threadpool, либо в asyncio-исполнителе; sync-
    логика проще и не блокирует event loop, если job уйдёт в threadpool.

    ``sync_connection_url`` — pydantic ``@computed_field``; mypy видит его
    как метод-property (Callable[[], str]), поэтому приводим к ``str`` явно.
    """
    from src.backend.core.config.settings import settings

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


def _resolve_snapshot_tenant(explicit_tenant_id: str | None = None) -> str:
    """Определить tenant-скоуп snapshot'а (ADR-0409).

    Приоритет: явный аргумент → tenant-контекст процесса. Системный
    tenant **не подставляется**: под RLS это дало бы 0 строк без ошибки
    (тихая потеря fallback'а ``db_main``).

    Args:
        explicit_tenant_id: Явный tenant_id (приоритет над контекстом).

    Returns:
        Идентификатор tenant'а для ``app.tenant_id``.

    Raises:
        SnapshotTenantScopeError: Tenant-скоуп не определён.

    """
    tenant_id = (explicit_tenant_id or "").strip()
    if tenant_id:
        return tenant_id

    from src.backend.core.tenancy import get_tenant_id

    context_tenant = (get_tenant_id() or "").strip()
    if context_tenant:
        return context_tenant

    raise SnapshotTenantScopeError(
        "Snapshot: tenant-скоуп не определён. Снапшот покрывает ровно "
        "один tenant (ADR-0409) — передайте tenant_id явно или выполните "
        "job в tenant-контексте. Межtenant-снимок требует служебной роли "
        "с BYPASSRLS (ADR-0393)."
    )


def _apply_tenant_scope(pg_conn: Connection, tenant_id: str) -> None:
    """Выставить ``app.tenant_id`` на PG-соединении (ADR-0400).

    Без этого PostgreSQL-RLS-политика
    (``tenant_id = current_setting('app.tenant_id', true)``) отдаёт 0 строк
    — снимок получается пустым без ошибки.

    Args:
        pg_conn: PG-соединение (транзакция открыта неявно первым execute).
        tenant_id: Идентификатор tenant'а для ``app.tenant_id``.

    Returns:
        None.
    """
    pg_conn.execute(text(_TENANT_SCOPE_SQL), {"tenant_id": tenant_id})


def _resolve_snapshot_mode() -> str:
    """Определить режим межtenant-снапшота из конфигурации (ADR-0413).

    Args:
        None.

    Returns:
        Один из режимов: ``single-tenant`` / ``per-tenant`` / ``service-role``.

    Raises:
        SnapshotModeError: В конфигурации указано неизвестное значение режима.

    """
    from src.backend.core.config.settings import settings

    modes = (_MODE_SINGLE_TENANT, _MODE_PER_TENANT, _MODE_SERVICE_ROLE)
    mode = str(settings.snapshot.mode or _MODE_SINGLE_TENANT)
    if mode not in modes:
        raise SnapshotModeError(
            f"Snapshot: неизвестный режим {mode!r} (snapshot.mode). "
            f"Допустимо: {', '.join(modes)}."
        )
    return mode


def _resolve_configured_tenants() -> list[str]:
    """Явный список tenant'ов для режима ``per-tenant`` (ADR-0413).

    Args:
        None.

    Returns:
        Список непустых tenant_id из ``snapshot.tenants``.

    Raises:
        SnapshotModeError: Список пуст — fail-closed (снимок не пишется).

    """
    from src.backend.core.config.settings import settings

    raw = settings.snapshot.tenants or []
    tenants = [str(item).strip() for item in raw if str(item).strip()]
    if not tenants:
        raise SnapshotModeError(
            "Snapshot: режим 'per-tenant' требует явного списка tenant'ов "
            "(snapshot.tenants / SNAPSHOT_TENANTS). Список пуст — снимок не "
            "пишется, иначе получился бы тихий 0-строчный снимок."
        )
    return tenants


def _resolve_service_dsn() -> str:
    """DSN служебной роли с ``BYPASSRLS`` для режима ``service-role``.

    Args:
        None.

    Returns:
        Строка DSN (sync-драйвер psycopg).

    Raises:
        SnapshotModeError: DSN не задан — fail-closed (снимок не пишется).

    """
    from src.backend.core.config.settings import settings

    secret = settings.snapshot.service_dsn
    dsn = secret.get_secret_value().strip() if secret is not None else ""
    if not dsn:
        raise SnapshotModeError(
            "Snapshot: режим 'service-role' требует явного DSN служебной "
            "роли с BYPASSRLS (snapshot.service_dsn / SNAPSHOT_SERVICE_DSN). "
            "Процедура выдачи роли — docs/ops/snapshot-bypassrls-role.md."
        )
    return dsn


def _assert_bypassrls(pg_conn: Connection) -> None:
    """Проверить, что роль соединения реально обходит RLS (ADR-0413).

    Без ``BYPASSRLS`` служебный DSN вернул бы 0 строк без ошибки — тихий
    пустой снимок. Проверка выполняется ДО выборки.

    Args:
        pg_conn: PG-соединение служебной роли.

    Returns:
        None.

    Raises:
        SnapshotModeError: У роли нет ``BYPASSRLS``.

    """
    bypass = pg_conn.execute(text(_BYPASSRLS_CHECK_SQL)).scalar()
    if not bypass:
        raise SnapshotModeError(
            "Snapshot: у пользователя служебного DSN нет BYPASSRLS — выборка "
            "вернула бы 0 строк (тихий пустой снимок). Выдайте роль по "
            "docs/ops/snapshot-bypassrls-role.md."
        )


def _read_table_rows(pg_conn: Connection, table: Table) -> list[dict[str, Any]]:
    """Прочитать все строки таблицы из PG.

    Args:
        pg_conn: PG-соединение (tenant-скоуп уже выставлен, если нужен).
        table: Таблица-источник.

    Returns:
        Список строк как dict'ы.

    """
    # Читаем все строки из PG — для read-only critical таблиц это
    # компактные lookup'ы (orderkinds / users / orders), не миллионы строк.
    return [dict(row) for row in pg_conn.execute(select(table)).mappings().all()]


def _write_table_rows(
    sqlite_conn: Connection, table: Table, rows: list[dict[str, Any]]
) -> int:
    """Записать строки таблицы в SQLite-снимок: ``DELETE FROM tbl; INSERT ...``.

    Args:
        sqlite_conn: Соединение SQLite (транзакция открыта).
        table: Таблица-приёмник.
        rows: Строки для вставки.

    Returns:
        Кол-во вставленных строк.

    """
    # Транзакционная замена.
    sqlite_conn.execute(delete(table))
    if rows:
        sqlite_conn.execute(insert(table), rows)
    return len(rows)


def sync_pg_to_sqlite(
    pg_engine: Engine,
    sqlite_engine: Engine,
    tables: list[str],
    *,
    tenant_id: str | None = None,
) -> dict[str, int]:
    """Реплицирует список таблиц из PG в SQLite-snapshot (один tenant).

    Режим ``single-tenant`` (ADR-0409/ADR-0413): tenant-скоуп обязателен.
    Межtenant-режимы — ``sync_multi_tenant_pg_to_sqlite`` (per-tenant) и
    ``sync_service_role_pg_to_sqlite`` (служебная роль с BYPASSRLS).

    Args:
        pg_engine: SYNC SQLAlchemy engine, указывающий на PostgreSQL.
        sqlite_engine: SYNC SQLAlchemy engine, указывающий на SQLite-файл.
        tables: упорядоченный список имён таблиц (FK-таблицы первыми).
        tenant_id: Явный tenant-скоуп снимка. Если не задан — берётся
            из tenant-контекста процесса.

    Returns:
        Словарь ``{table_name: rows_replicated}`` для всех успешно
        реплицированных таблиц.

    Raises:
        SnapshotTenantScopeError: Tenant-скоуп не определён (fail-closed,
            ADR-0409) — снимок не пишется.
        Любое исключение SQLAlchemy. Вызывающая сторона (планировщик
        или ``run_snapshot_now``) обязана обработать его и
        инкрементировать ``snapshot_sync_errors_total``.

    """
    target_tables = _resolve_target_tables(tables)
    if not target_tables:
        logger.warning("Snapshot: список таблиц пуст — нечего реплицировать")
        return {}

    # ADR-0409: tenant-скоуп обязателен и определяется ДО записи в SQLite —
    # при отсутствии скоупа файл snapshot'а остаётся нетронутым (fail-closed).
    resolved_tenant = _resolve_snapshot_tenant(tenant_id)

    return _sync_snapshot(
        pg_engine,
        sqlite_engine,
        target_tables,
        scopes=[(_SCOPE_TENANT, resolved_tenant)],
        strict=False,
    )


def sync_multi_tenant_pg_to_sqlite(
    pg_engine: Engine,
    sqlite_engine: Engine,
    tables: list[str],
    *,
    tenant_ids: list[str],
) -> dict[str, int]:
    """Реплицировать снимок по ЯВНОМУ списку tenant'ов (ADR-0413, per-tenant).

    Безопасная альтернатива роли с ``BYPASSRLS``: для каждого tenant'а
    выставляется собственный ``app.tenant_id``, поэтому RLS остаётся
    включённым — служебная роль не нужна.

    Args:
        pg_engine: SYNC SQLAlchemy engine, указывающий на PostgreSQL.
        sqlite_engine: SYNC SQLAlchemy engine, указывающий на SQLite-файл.
        tables: упорядоченный список имён таблиц (FK-таблицы первыми).
        tenant_ids: Явный список tenant'ов. Пустой — fail-closed.

    Returns:
        Словарь ``{table_name: rows_replicated}`` (сумма по всем tenant'ам).

    Raises:
        SnapshotModeError: Список tenant'ов пуст или снимок пуст — снимок
            не пишется (предыдущий валидный снимок сохраняется).

    """
    tenants = [str(item).strip() for item in tenant_ids if str(item).strip()]
    if not tenants:
        raise SnapshotModeError(
            "Snapshot: режим 'per-tenant' требует явного списка tenant'ов. "
            "Список пуст — снимок не пишется (иначе получился бы тихий "
            "0-строчный снимок)."
        )

    target_tables = _resolve_target_tables(tables)
    if not target_tables:
        logger.warning("Snapshot: список таблиц пуст — нечего реплицировать")
        return {}

    return _sync_snapshot(
        pg_engine,
        sqlite_engine,
        target_tables,
        scopes=[(_SCOPE_TENANT, tenant) for tenant in tenants],
        strict=True,
    )


def sync_service_role_pg_to_sqlite(
    pg_engine: Engine, sqlite_engine: Engine, tables: list[str]
) -> dict[str, int]:
    """Реплицировать снимок служебной ролью с ``BYPASSRLS`` (ADR-0413).

    Соединение должно быть открыто DSN'ом служебной роли
    (``snapshot.service_dsn``): наличие ``BYPASSRLS`` проверяется до
    выборки, иначе снимок был бы тихо пустым.

    Args:
        pg_engine: SYNC SQLAlchemy engine служебной роли.
        sqlite_engine: SYNC SQLAlchemy engine, указывающий на SQLite-файл.
        tables: упорядоченный список имён таблиц (FK-таблицы первыми).

    Returns:
        Словарь ``{table_name: rows_replicated}``.

    Raises:
        SnapshotModeError: У роли нет ``BYPASSRLS`` или снимок пуст —
            снимок не пишется.

    """
    target_tables = _resolve_target_tables(tables)
    if not target_tables:
        logger.warning("Snapshot: список таблиц пуст — нечего реплицировать")
        return {}

    return _sync_snapshot(
        pg_engine,
        sqlite_engine,
        target_tables,
        scopes=[(_SCOPE_SERVICE_ROLE, None)],
        strict=True,
    )


def _resolve_target_tables(tables: list[str]) -> list[Table]:
    """Поднять ORM-модули плагинов и вернуть целевые таблицы.

    Поднятие ORM-модулей плагинов обязательно для регистрации таблиц в
    ``metadata.tables`` — иначе ``metadata.create_all`` создаст пустую
    структуру.

    Cycle-15 (D-AUDIT-1502): вместо неявных side-effect импортов через
    ``core/domain/models/__init__.py`` (которые и создавали слой
    core→extensions в гейте) идём через
    :func:`load_plugin_manifests_for_migrations`, читая ``models_module``
    из каждого ``extensions/<name>/plugin.toml``. Этот же путь использует
    ``src/backend/infrastructure/database/migrations/env.py`` для
    alembic autogenerate.

    Args:
        tables: Упорядоченный список имён таблиц.

    Returns:
        Список существующих ``Table``-объектов (неизвестные имена
        пропускаются с warning).

    """
    from src.backend.core.domain.models.base import metadata
    from src.backend.services.plugins.loader import load_plugin_manifests_for_migrations

    try:
        for _mwp in load_plugin_manifests_for_migrations(
            Path(__file__).resolve().parents[5] / "extensions"
        ):
            for _module_path in _mwp.manifest.models_module:
                try:
                    importlib.import_module(_module_path)
                except ImportError:
                    logger.debug("snapshot: models_module %s недоступен", _module_path)
    except ImportError:
        logger.debug("snapshot: models_discovery недоступен — пропуск регистрации")

    return _select_tables(metadata.tables, tables)


def _sync_snapshot(
    pg_engine: Engine,
    sqlite_engine: Engine,
    target_tables: list[Table],
    *,
    scopes: list[tuple[str, str | None]],
    strict: bool,
) -> dict[str, int]:
    """Реплицировать таблицы из PG в SQLite по списку областей чтения.

    Args:
        pg_engine: SYNC SQLAlchemy engine, указывающий на PostgreSQL.
        sqlite_engine: SYNC SQLAlchemy engine, указывающий на SQLite-файл.
        target_tables: Целевые таблицы (уже разрешённые в metadata).
        scopes: Области чтения: ``("tenant", tenant_id)`` — чтение с
            per-tenant ``SET app.tenant_id``; ``("service-role", None)`` —
            чтение служебной ролью с ``BYPASSRLS`` (проверяется до выборки).
        strict: ``True`` — строгий межtenant-режим: пустой снимок — ошибка
            (файл снимка не пишется), пустые таблицы логируются WARNING'ом.
            ``False`` — режим single-tenant: пустой снимок — WARNING
            (ADR-0409).

    Returns:
        Словарь ``{table_name: rows_replicated}``.

    Raises:
        SnapshotModeError: Пустой снимок в строгом режиме либо у служебной
            роли нет ``BYPASSRLS``.

    """
    # DDL: создаём только нужные таблицы в SQLite (idempotent).
    from src.backend.core.domain.models.base import metadata

    metadata.create_all(sqlite_engine, tables=target_tables, checkfirst=True)

    collected: dict[str, list[dict[str, Any]]] = {
        table.name: [] for table in target_tables
    }

    with pg_engine.connect() as pg_conn, sqlite_engine.begin() as sqlite_conn:
        for scope_kind, scope_value in scopes:
            if scope_kind == _SCOPE_SERVICE_ROLE:
                # ADR-0413: без BYPASSRLS выборка вернула бы 0 строк.
                _assert_bypassrls(pg_conn)
                scope_label = _SCOPE_SERVICE_ROLE
            else:
                # ADR-0400: tenant-скоуп ДО выборки — иначе RLS вернёт
                # 0 строк (тихая потеря снапшота).
                _apply_tenant_scope(pg_conn, scope_value or "")
                scope_label = scope_value or ""

            for table in target_tables:
                rows = _read_table_rows(pg_conn, table)
                collected[table.name].extend(rows)
                logger.info(
                    "Snapshot: '%s' прочитана (%d строк, scope=%s)",
                    table.name,
                    len(rows),
                    scope_label,
                )
                if strict and not rows:
                    logger.warning(
                        "Snapshot: '%s' — 0 строк (scope=%s): проверьте "
                        "tenant-скоуп и наличие данных в PG",
                        table.name,
                        scope_label,
                    )

        total_rows = sum(len(rows) for rows in collected.values())
        if strict and total_rows == 0:
            # Fail-closed ДО записи: файл снимка не затирается пустым.
            raise SnapshotModeError(
                "Snapshot: снимок пуст (0 строк по всем таблицам) — запись "
                "пропущена, предыдущий снимок сохранён. Проверьте список "
                "tenant'ов / наличие BYPASSRLS у служебной роли."
            )

        rows_per_table: dict[str, int] = {}
        for table in target_tables:
            count = _write_table_rows(sqlite_conn, table, collected[table.name])
            rows_per_table[table.name] = count
            logger.info("Snapshot: '%s' реплицирована (%d строк)", table.name, count)

    if not any(rows_per_table.values()):
        logger.warning(
            "Snapshot: снимок пуст (0 строк по всем таблицам) — fallback "
            "db_main отдаст пустые данные; проверьте tenant-скоуп и "
            "наличие данных в PG"
        )

    return rows_per_table


def run_snapshot_now(tenant_id: str | None = None) -> dict[str, int]:
    """Синхронный entry-point для startup hook / manual-trigger.

    Создаёт engine'ы, выполняет sync, обновляет внутреннее состояние и
    публикует метрики. Безопасен к повторным вызовам (idempotent —
    DELETE+INSERT в одной транзакции).

    Режим межtenant-снапшота определяется конфигурацией ``snapshot.mode``
    (ADR-0413): ``single-tenant`` (по умолчанию) / ``per-tenant`` /
    ``service-role``. Аргумент ``tenant_id`` имеет смысл только в
    режиме ``single-tenant``.

    Args:
        tenant_id: Явный tenant-скоуп снимка (режим ``single-tenant``). Если
            не задан — берётся из tenant-контекста процесса; если скоупа
            нет — fail-closed (ADR-0409), snapshot-файл не перезаписывается.

    Returns:
        Словарь ``{table_name: rows_replicated}``.

    Raises:
        SnapshotTenantScopeError: Tenant-скоуп не определён (режим
            ``single-tenant``).
        SnapshotModeError: Режим сконфигурирован некорректно (пустой список
            tenant'ов, отсутствие service-DSN, нет ``BYPASSRLS`` у роли).

    """
    global _last_sync_ts, _last_sync_duration, _last_sync_rows

    from src.backend.core.config.settings import settings

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
        # ADR-0413: режим межtenant-снапшота определяется из конфигурации.
        mode = _resolve_snapshot_mode()

        # ADR-0409/ADR-0413: всё, что может отказать, определяется ДО
        # создания движков, чтобы при отказе snapshot-файл остался
        # нетронутым (fail-closed).
        if mode == _MODE_PER_TENANT:
            tenants = _resolve_configured_tenants()
            pg_url = _build_pg_url()
        elif mode == _MODE_SERVICE_ROLE:
            tenants = []
            pg_url = _resolve_service_dsn()
        else:
            tenants = []
            pg_url = _build_pg_url()
            resolved_tenant = _resolve_snapshot_tenant(tenant_id)

        pg_engine = create_engine(pg_url, pool_pre_ping=True)
        sqlite_engine = create_engine(_build_sqlite_url(snapshot_cfg.target_path))

        if mode == _MODE_PER_TENANT:
            rows = sync_multi_tenant_pg_to_sqlite(
                pg_engine, sqlite_engine, snapshot_cfg.tables, tenant_ids=tenants
            )
        elif mode == _MODE_SERVICE_ROLE:
            rows = sync_service_role_pg_to_sqlite(
                pg_engine, sqlite_engine, snapshot_cfg.tables
            )
        else:
            rows = sync_pg_to_sqlite(
                pg_engine, sqlite_engine, snapshot_cfg.tables, tenant_id=resolved_tenant
            )

        _last_sync_ts = time.time()
        _last_sync_duration = time.perf_counter() - started
        _last_sync_rows = rows
        _publish_metrics()

        logger.info(
            "Snapshot: sync завершён за %.2fs, %d таблиц, %d строк всего (режим=%s)",
            _last_sync_duration,
            len(rows),
            sum(rows.values()),
            mode,
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
        from src.backend.core.config.settings import settings

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


def register_snapshot_job(scheduler: Any, tenant_id: str | None = None) -> None:
    """Регистрирует snapshot job в APScheduler-инстансе.

    Использует ``IntervalTrigger`` (cron-like период
    ``snapshot.interval_minutes``). Job выполняется в threadpool-
    executor'е (sync-логика); в SQLAlchemyJobStore сохраняется по
    ``SNAPSHOT_JOB_ID`` для idempotent-перезапуска.

    Если ``snapshot.enabled=false`` — job НЕ регистрируется.

    Args:
        scheduler: APScheduler-инстанс.
        tenant_id: Tenant-скоуп для периодического job'а. Если не задан —
            job работает в tenant-контексте процесса, а при его
            отсутствии каждый запуск падает fail-closed (ADR-0409).
            В режимах ``per-tenant`` / ``service-role`` (ADR-0413) скоуп
            берётся из конфигурации, поэтому аргумент не требуется.

    """
    from src.backend.core.config.settings import settings

    snapshot_cfg = settings.snapshot
    if not snapshot_cfg.enabled:
        logger.info("Snapshot: job не регистрируется (snapshot.enabled=false)")
        return

    mode = _resolve_snapshot_mode()

    job_kwargs: dict[str, Any] = {}
    if tenant_id:
        job_kwargs["tenant_id"] = tenant_id
    elif mode == _MODE_SINGLE_TENANT:
        logger.warning(
            "Snapshot: job зарегистрирован без tenant-скоупа — каждый запуск "
            "завершится fail-closed ошибкой (ADR-0409), если процесс не "
            "исполняется в tenant-контексте"
        )
    else:
        logger.info(
            "Snapshot: job зарегистрирован в режиме '%s' — tenant-скоуп "
            "берётся из конфигурации (ADR-0413)",
            mode,
        )

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
        kwargs=job_kwargs,
    )
    logger.info(
        "Snapshot: job '%s' зарегистрирован (interval=%d min, %d таблиц, режим=%s)",
        SNAPSHOT_JOB_ID,
        snapshot_cfg.interval_minutes,
        len(snapshot_cfg.tables),
        mode,
    )


# ──────────────────────────────────────────────────────────────────────
# S168 W11 P2-5: SnapshotJob class wrapper (minimal class-ification).
# ──────────────────────────────────────────────────────────────────────
#
# Per master prompt v8 P2-5: "wrap in SnapshotJob class with private
# _persist(), _restore(), _rotate() to make state explicit and enable
# DI for testing". This commit adds the CLASS SHELL only — module-level
# state and functions остаются canonical (backward-compat).
# Full class-ification (state migration) — separate WIP.
# ──────────────────────────────────────────────────────────────────────

import threading


class SnapshotJob:
    """S168 W11 P2-5: thin class wrapper around module-level state.

    Per Ponytail minimum, current implementation:
    - module-level state (per S168) maintained для backward-compat
    - class holds reference to global state via read-only properties
    - ``run_once()`` метод delegates to module-level ``run_snapshot_now()``

    Migration path (separate WIP):
    - Move _last_sync_ts, _last_sync_duration, _last_sync_rows to instance
    - Add ``_persist()``, ``_restore()``, ``_rotate()`` methods
    - DI for testing (replace module-level state with mockable instance)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_run_at: float | None = None
        self._last_duration_s: float = 0.0
        self._last_rows: dict[str, int] = {}

    @property
    def last_run_at(self) -> float | None:
        """Timestamp последнего успешного snapshot (UNIX epoch)."""
        return self._last_run_at

    @property
    def last_duration_s(self) -> float:
        """Метод last_duration_s (см. signature)."""
        return self._last_duration_s

    @property
    def last_rows(self) -> dict[str, int]:
        """Метод last_rows (см. signature)."""
        return dict(self._last_rows)

    def run_once(self) -> dict[str, int]:
        """Запустить snapshot sync (delegates to module-level run_snapshot_now).

        Returns:
            dict[table_name, row_count] для replicated tables.

        """
        with self._lock:
            result = run_snapshot_now()
            self._last_run_at = time.time()
            self._last_duration_s = _last_sync_duration
            self._last_rows = dict(_last_sync_rows)
        return result


_snapshot_job_singleton: SnapshotJob | None = None


def get_snapshot_job() -> SnapshotJob:
    """Singleton accessor для SnapshotJob instance (S168 W11 P2-5).

    Returns:
        module-level singleton (lazy-initialized).

    """
    global _snapshot_job_singleton
    if _snapshot_job_singleton is None:
        _snapshot_job_singleton = SnapshotJob()
    return _snapshot_job_singleton
