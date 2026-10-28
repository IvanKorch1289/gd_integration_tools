# ADR-0363 — Драйверы БД: psycopg3 как sync-дефолт, fail-fast на необъявленный драйвер, гейт объявленных зависимостей

* Статус: ACCEPTED (2026-10-27, cycle 172, Wave 13 — решения Q8 + Q9)
* Cycle: 172
* Дата: 2026-10-27
- **Затрагивает**: `src/backend/core/config/database.py`,
  `src/backend/core/config/db_drivers.py`,
  `src/backend/infrastructure/clients/storage/clickhouse_driver.py`,
  `tools/check_dsn_drivers.py`, `tools/check_declared_dependencies.py`
- **Связан с**: ADR-0350 (удаление мёртвого кода), ADR-0335 (unsafe-defaults),
  `docs/roadmap/PROD_READINESS_GAPS.md` § G11

## Контекст

### Дефолт sync-драйвера PostgreSQL не существует

`DatabaseConnectionSettings.sync_driver` (`src/backend/core/config/database.py:74-82`)
по умолчанию был `"psycopg2"`. Проверено в окружении: `psycopg2` **не
установлен** (`importlib.util.find_spec("psycopg2")` → `None`), и **не
объявлен ни в одном extra** — в `[project.optional-dependencies]` нет ни
одной строки с `psycopg2`. Установлен psycopg3 (`psycopg` 3.3.5 +
`psycopg-binary` 3.3.5), объявленный в extra `sources-cdc`
(`pyproject.toml:498-500`, `psycopg[binary]>=3.1,<4.0.0`).

Итог: дефолтный sync-движок неработоспособен «из коробки», а ошибка
возникала поздно и невнятно.

### DSN-конструкторы обещают необъявленные драйверы

`src/backend/core/config/database.py:262-266` — для MSSQL sync-дривером
подставляется `pyodbc`, async — `aioodbc`. `aioodbc` объявлен в extra
`db_drivers` (`pyproject.toml:212-216`: `oracledb`, `aioodbc`, `aiomysql`),
а **`pyodbc` не объявлен ни в одном extra** — в текущем venv он приезжает
только транзитивно, вместе с `aioodbc` 0.5.0 (`aioodbc -> pyodbc >=5.0.1`).
Аналогично `ibm_db_sa` (DB2) не объявлен нигде.

### «Висячая зависимость» — класс дефекта, а не разовый случай

Пакет `clickhouse_connect` импортировался в **6 местах** `src/backend/`
(проверено по `HEAD`; номера строк — в версии до этой волны):

| Место импорта (HEAD) | Поведение при отсутствии пакета |
|---|---|
| `services/audit/clickhouse_audit_service/service.py:119` | `ModuleNotFoundError` (без fallback) |
| `services/workflows/saga_history.py:40` | `ModuleNotFoundError` |
| `services/workflows/hitl_history.py:64` | `ModuleNotFoundError` |
| `services/workflows/cost_estimator.py:77` | `ModuleNotFoundError` |
| `services/scheduler/cron_dashboard_service.py:49` | тихая деградация (`except Exception: return None`) |
| `infrastructure/clients/storage/clickhouse_admin_client.py:45` | деградация + WARNING |

4 из 6 падали, 2 — молчаливая деградация. При этом `clickhouse_connect`
**не объявлен ни в `[project].dependencies`, ни в одном extra** — только как
mypy-override (`pyproject.toml:1044-1045`), то есть сам пакет в окружении
отсутствует (`find_spec("clickhouse_connect")` → `None`).

## Решение

### (а) Sync-дефолт PostgreSQL — `psycopg` (psycopg3)

`core/config/database.py:74-82`: дефолт `sync_driver` = `"psycopg"`.
Псиcopg3 умеет и sync, и async, уже установлен и уже объявлен (extra
`sources-cdc`). Прогнан тот же путь в `config_profiles/base.yml:171`
(`sync_driver: "psycopg"`) и в `config_profiles/dev.yml:80`.

### (б) `core/config/db_drivers.py` — реестр объявлений + fail-fast

Новый модуль `src/backend/core/config/db_drivers.py` (125 LOC, зависит
только от stdlib — его импортирует CI-гейт без поднятия конфигурации):

* `DriverDeclaration` / `DB_DRIVER_DECLARATIONS` (`db_drivers.py:37-71`) —
  источник истины «как проект объявляет драйвер» (extra + дистрибуция);
* `DatabaseDriverError` (`db_drivers.py:74-79`) — доменная ошибка вместо
  позднего `ModuleNotFoundError` из SQLAlchemy;
* `is_driver_installed` (`db_drivers.py:82-95`) — проверка через
  `importlib.util.find_spec` (без импорта: импорт драйвера тянет нативные
  библиотеки);
* `ensure_driver_available` (`db_drivers.py:97-125`) — fail-fast с двумя
  разными сообщениями: «драйвер X **не объявлен** ни в одном extra» и
  «драйвер X **объявлен** в extra Y, **но не установлен**».

Вызовы: `core/config/database.py:233` (sqlite), `core/config/database.py:238`
(общий путь), `core/config/external_databases/connection.py:160` (внешние
БД) — до сборки DSN.

**Async-first сохранён**: sync-движок при такой ошибке **не валит старт** —
`DatabaseInitializer` перехватывает `(ModuleNotFoundError, DatabaseDriverError)`
(`src/backend/infrastructure/database/database/initializer.py:91-100`),
пишет warning и оставляет `sync_engine = None` (контракт Wave F.3).

### (в) `tools/check_dsn_drivers.py` — декларативная проверка

Гейт расширен: он не только проверяет импортируемость драйвера в текущем
venv (`check_all_drivers`, `tools/check_dsn_drivers.py:148`), но и сверяет
DSN-конструкторы с объявленными дистрибуциями (`DSN_DRIVER_MAP`,
`tools/check_dsn_drivers.py:64-71`; сбор ссылок из кода —
`collect_driver_references`, `tools/check_dsn_drivers.py:276`;
сверка — `check_driver_declarations`, `tools/check_dsn_drivers.py:326`).

Baseline известного долга — `tools/check_dsn_drivers_allowlist.txt`:
**2 записи** — `pyodbc` (MSSQL sync) и `ibm_db_sa` (DB2 sync).

### (г) Единая точка импорта clickhouse-драйвера

Новый модуль `src/backend/infrastructure/clients/storage/clickhouse_driver.py`
(145 LOC) закрывает **класс** дефекта, а не симптом:

* `import_clickhouse_driver(required=True)` (`clickhouse_driver.py:78-106`) —
  доменная ошибка `ClickHouseDriverError` (`clickhouse_driver.py:52-75`) с
  указанием пакета и extra (`db_drivers`);
* `required=False` → `None` + WARNING (`clickhouse_driver.py:99-104`) —
  деградация для путей чтения UI;
* `create_clickhouse_async_client` (`clickhouse_driver.py:109-145`) — единая
  точка чтения параметров подключения, чтобы 6 потребителей не разъезжались.

Расклад по потребителям (fail-loud для путей записи, деградация для UI):
`clickhouse_audit_service/service.py:127` (required=True),
`workflows/saga_history.py:58`, `workflows/hitl_history.py:79`,
`workflows/cost_estimator.py:92` — required=True;
`infrastructure/clients/storage/clickhouse_admin_client.py:54` и
`services/scheduler/cron_dashboard_service.py:64` — required=False.

Молчаливая потеря audit-событий недопустима — это и есть причина
fail-loud для write-путей.

### (д) Гейт объявленных зависимостей

Новый `tools/check_declared_dependencies.py` + baseline
`tools/check_declared_dependencies_allowlist.txt` (**78 записей**).
Гейт делает AST-скан статических импортов в `src/` и `tests/`
(`scan_tree`, `tools/check_declared_dependencies.py:264`) и сверяет их с
дистрибуциями из `pyproject.toml` (`declared_distributions`,
`tools/check_declared_dependencies.py:183`); несовпадение имён вида
«модуль → дистрибуция» задаётся вручную
(`IMPORT_NAME_TO_DISTRIBUTION`, `tools/check_declared_dependencies.py:108`).

`clickhouse_connect` зафиксирован в baseline как известный долг с
owner-задачей (`tools/check_declared_dependencies_allowlist.txt:20`).
Прогон гейта: «Необъявленных зависимостей: 0 новых (всего в долге: 78)».
CI-шаг — `.github/workflows/lint.yml:112-115`.

### (е) Объявление `clickhouse_connect` и `pyodbc` в extra — ВЫПОЛНЕНО

**Согласовано владельцем** (гриллинг, раунд 2, Q2) — lock-чанж разрешён:

- `clickhouse-connect>=0.7.0,<1.0.0` и `pyodbc>=5.0.0,<6.0.0` добавлены в
  extra `db_drivers` (`pyproject.toml:216-217`), lock-файл обновлён
  (`uv lock` → 681 пакет, `uv lock --check` — зелёный);
- `clickhouse_connect` снят из baseline
  `tools/check_declared_dependencies_allowlist.txt` (78 → 77 записей);
  `pyodbc` снят из `tools/check_dsn_drivers_allowlist.txt` (в долге остался
  только проприетарный `ibm_db_sa`);
- `DB_DRIVER_DECLARATIONS` (`core/config/db_drivers.py`) дополнен записями
  `pyodbc` и `clickhouse_connect` → рантайм-guard больше не отвергает их;
- DSN MSSQL sync теперь собирается: `mssql+pyodbc://sa:P%40ssw0rd@host:1433/db`
  (пароль URL-кодируется, `quote_plus`).

Не объявлено (и остаётся в долге): `ibm_db_sa` — проприетарный пакет
(требует установки IBM DB2), в публичных extras недоступен.

## Альтернативы (отклонённые)

### (а) Объявить зависимости сразу — отклонено на момент ADR, реализовано позже

Правка `pyproject.toml` + lock-файла — lock-чанж, запрещённый без
согласования (Sprint 36). Отложено как owner-задача G11; **согласовано
владельцем в гриллинге раунда 2 (Q2) и выполнено** — см. решение (е).

### (б) Оставить `psycopg2` и требовать установки — отклонено

В окружении драйвера нет, в extras он не объявлен — дефолтный sync-движок
неработоспособен «из коробки», а требование «доставьте драйвер сами» не
решается ничем, кроме как правкой extras (пункт (а)).

### (в) Молчаливая деградация clickhouse — отклонено

Молчаливая деградация допустима только для путей чтения UI (дашборд cron,
админ-клиент). Для путей записи (audit-события, saga/HITL-история, оценка
стоимости) потеря данных хуже явной ошибки — отсюда `required=True` и
доменное исключение вместо `ModuleNotFoundError`.

## Последствия

### Позитивные

- Дефолтный PG sync-драйвер **работоспособен** без ручных действий.
- Необъявленный драйвер даёт **понятную ошибку с именем extra** вместо
  `ModuleNotFoundError` внутри SQLAlchemy.
- Класс «висячих зависимостей» закрыт гейтом: 78 записей baseline, новые
  падают в CI.
- ClickHouse-пути записи fail-loud, пути чтения UI — деградируют с WARNING.

### Негативные

- **`psycopg` объявлен в extra `sources-cdc`, а не в `db_drivers`** —
  сборка только `db_drivers` не даст sync-драйвера PG; это часть G11.
- **MSSQL/DB2 нельзя сконфигурировать без ручной установки драйвера**:
  `ensure_driver_available("pyodbc")` и `ensure_driver_available("ibm_db_sa")`
  поднимают `DatabaseDriverError` (драйвер не объявлен ни в одном extra),
  даже если пакет физически установлен в venv. Для compose-образа
  (`--extra dev-light`) `oracledb`/`aioodbc`/`aiomysql` тоже отсутствуют.
- Sync-движок в такой конфигурации остаётся `None` (`initializer.py:91-100`) —
  durable APScheduler jobstore заменяется на memory.

### Нейтрально

- Реестр `DB_DRIVER_DECLARATIONS` — источник истины для рантайм-guard'а и
  для CI-гейта одновременно; при изменении extras его нужно править.

## Проверка после реализации

```bash
# 1. Fail-fast на необъявленный драйвер
uv run python -c "
from src.backend.core.config.db_drivers import ensure_driver_available, DatabaseDriverError
try:
    ensure_driver_available('pyodbc')
except DatabaseDriverError as exc:
    print(exc)
"
# ожидаемо: «Драйвер 'pyodbc' не объявлен ни в одном extra проекта …»

# 2. Sync-дефолт PG
uv run python -c "
from src.backend.core.config.database import db_connection_settings
print(db_connection_settings.sync_driver)"   # ожидаемо: psycopg

# 3. Гейт DSN-драйверов: декларативная часть — без новых gap'ов
uv run python tools/check_dsn_drivers.py
# ожидаемо (секция «DSN driver declarations»):
#   «All referenced drivers are declared in extras.»
# ВНИМАНИЕ: exit code гейта зависит от состава venv — `--ci` падает и на
# недоступных драйверах (в текущем окружении MSSQL/DB2/clickhouse не
# установлены — это состояние окружения, не регрессия этого цикла).

# 4. Гейт объявленных зависимостей
uv run python tools/check_declared_dependencies.py
# ожидаемо: 0 новых (всего в долге: 78)

# 5. Юнит-тесты
uv run pytest tests/unit/core/config/test_dsn_driver_availability.py \
                tests/unit/core/config/test_no_orphan_config_keys.py \
                tests/unit/infrastructure/database/test_sync_driver_graceful_degradation.py \
                tests/unit/infrastructure/clients/storage/test_clickhouse_driver.py \
                tests/unit/tools/test_check_declared_dependencies.py \
                tests/unit/tools/test_check_dsn_drivers_declarations.py -q
```

## Статус реализации

**Cycle 172 (Wave 13).** Реализовано: решения (а), (б), (в), (г), (д) —
`core/config/db_drivers.py`, `core/config/database.py`,
`core/config/external_databases/connection.py`, `clickhouse_driver.py`,
`tools/check_dsn_drivers.py`, `tools/check_declared_dependencies.py` +
allowlist'ы, CI-шаги в `.github/workflows/lint.yml:112-115`.
Решение (е) — **выполнено после согласования владельцем** (гриллинг, раунд 2,
Q2): `clickhouse-connect` и `pyodbc` объявлены в extra `db_drivers`, lock
обновлён, allowlist'ы очищены.

## Followup (owner-задачи)

1. **G11 (частично закрыт).** `clickhouse-connect` и `pyodbc` объявлены;
   в долге остался проприетарный `ibm_db_sa` (DB2 sync) — требует установки
   IBM DB2, в публичных extras недоступен.
2. **`psycopg[binary]` и `aiosqlite`** объявлены не в `db_drivers`, а в
   `sources-cdc` / `dev-light` — sync-движок PostgreSQL в prod-образе,
   собранном без этих extra, деградирует в `None` + warning. Перенос
   `psycopg[binary]` в `db_drivers` — отдельное решение (увеличивает образ).
3. **Свести `DB_DRIVER_DECLARATIONS` с фактическим `pyproject.toml`**
   автоматически (сейчас реестр поддерживается вручную).

## Связи с другими ADR

- ADR-0350 — удаление мёртвого кода (тот же принцип: не оставлять
  неисполняемые/необъявленные сущности; сюда — драйвер, которого нет).
- ADR-0335 — гейт unsafe-defaults (неработоспособный дефолт `sync_driver`
  был ровно таким классом).
- ADR-0336 — env-example matrix (смежный класс: декларация без реальности).
- `docs/roadmap/PROD_READINESS_GAPS.md` § G11 — owner-задача по
  объявлению драйверов в extras.
