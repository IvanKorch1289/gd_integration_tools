# Cookbook 06: DSN Driver Availability

> Audience: devs configuring external databases (MSSQL, MySQL, DB2, Oracle).
> Time: 5-10 min.
> Difficulty: low.

## Problem

S104 W3 added support for **MSSQL**, **MySQL**, и **DB2** DSN types
(DEEP-RESEARCH D19). Драйверы для них — **optional dependencies**:

| DSN type | Sync driver | Async driver | Где объявлен |
|----------|-------------|--------------|--------------|
| `postgresql` | `psycopg` | `asyncpg` | `sources-cdc` / core |
| `sqlite` | `sqlite3` (stdlib) | `aiosqlite` | stdlib / `dev-light` |
| `mssql` | `pyodbc` | `aioodbc` | **не объявлен** / `db_drivers` |
| `mysql` | `pymysql` | `aiomysql` | `db_drivers` (pymysql — транзитивно с aiomysql) |
| `db2` | `ibm_db_sa` | `ibm_db` | **не объявлен** |
| `oracle` | `oracledb` | `oracledb` | `db_drivers` |

**Проблема (Wave 13 Q9):** DSN-конструкторы обещали драйверы, которых нет
в окружении (`psycopg2` — нет ни в одном extra, ни в lock-файле; `pyodbc`,
`ibm_db_sa` — не объявлены). Ошибка возникала только в **runtime** (в
`DatabaseInitializer`), и сообщение было obscure:
`ImportError: No module named 'pyodbc'`.

## Fail-fast в рантайме

`src/backend/core/config/database.py::_build_dsn` теперь проверяет драйвер
**до** сборки DSN (`src/backend/core/config/db_drivers.py`):

```python
from src.backend.core.config.db_drivers import DatabaseDriverError

try:
    dsn = settings.database.sync_connection_url
except DatabaseDriverError as exc:
    # "Драйвер 'pyodbc' не объявлен ни в одном extra проекта ... "
    ...
```

Правила:

* драйвер **не объявлен** ни в одном extra → `DatabaseDriverError` с
  подсказкой (какой extra нужно доустановить);
* драйвер **объявлен**, но не установлен в venv → `DatabaseDriverError` с
  указанием extra (`pip install 'gd-advanced-tools[db_drivers]'`).

Sync-engine в `DatabaseInitializer` при этом не валит старт: ошибка
перехватывается, `sync_engine=None` (контракт Wave F.3 — async-first).

## Tool: `tools/check_dsn_drivers.py`

S106 W7 (B Sprint W2) добавил CI-runnable check tool, который заранее
определяет какие DSN types реально готовы в текущем venv. Wave 13 Q9
добавил вторую проверку: **драйвер, упомянутый в DSN-конструкторе, должен
быть объявлен хотя бы в одном extra** (allowlist известного долга —
`tools/check_dsn_drivers_allowlist.txt`).

### Human-readable режим

```bash
$ .venv/bin/python tools/check_dsn_drivers.py
DSN driver availability
============================================================
  postgresql   | sync=psycopg      [OK ] | async=asyncpg      [OK ]
  sqlite       | sync=sqlite3      [OK ] | async=aiosqlite    [OK ]
  mssql        | sync=pyodbc       [MISS] | async=aioodbc      [MISS]
  mysql        | sync=pymysql      [OK ] | async=aiomysql     [OK ]
  db2          | sync=ibm_db_sa    [MISS] | async=ibm_db       [MISS]
  oracle       | sync=oracledb     [OK ] | async=oracledb     [OK ]
============================================================
MISSING drivers — install via pip extras:
  pip install pyodbc
  pip install aioodbc
  ...
DSN driver declarations
============================================================
All referenced drivers are declared in extras.
```

Exit 0 (no CI gate).

### CI режим

```bash
$ .venv/bin/python tools/check_dsn_drivers.py --ci
... (same output)
$ echo $?
1
```

Exit 1 если хотя бы один driver missing **или** есть необъявленный драйвер
(вне allowlist). Use в pre-deploy gate:
```bash
# In CI pipeline
python tools/check_dsn_drivers.py --ci || {
    echo "FATAL: missing/undeclared DSN drivers. Run 'pip install ...' first."
    exit 1
}
```

## Install patterns

### Single driver
```bash
pip install pyodbc
```

### Full set (all DSN types)
```bash
# Note: некоторые drivers требуют system-level ODBC headers (Linux)
# For MSSQL on Linux:
sudo apt install unixodbc-dev
pip install pyodbc aioodbc

# For DB2:
pip install ibm-db-sa ibm_db

# For Oracle:
pip install oracledb
```

### Project extras

Драйверы, объявленные проектом, ставятся extras'ами:

```bash
uv sync --extra db_drivers      # oracledb, aioodbc, aiomysql (+pymysql)
uv sync --extra sources-cdc     # psycopg[binary] — sync/async PostgreSQL
```

`pyodbc`/`ibm_db_sa` в extras пока **нет** (Sprint 36: правка
`pyproject.toml` + lock-файла) — до тех пор DSN с ними отвергается
fail-fast'ом.

## Known caveats

- **`psycopg` (psycopg3)** — объявлен в extra `sources-cdc`; умеет и sync,
  и async. Старый `psycopg2` из проекта удалён (нет ни в одном extra, ни в
  lock-файле).
- **`ibm_db`** — closed-source IBM драйвер, может быть недоступен на
  некоторых архитектурах. Fallback: `ibm_db_sa` (pure Python SQLAlchemy
  adapter) — НЕ async-friendly, но работает для sync.
- **`aioodbc`** — async обёртка над pyodbc, требует тот же system
  ODBC manager. Без `unixodbc-dev` на Linux `pip install aioodbc` упадёт.

## Related

- ADR-0192 (S106 closure, planned)
- `docs/migration/d5-models-to-core.md` (related: DSN parsing в DatabaseConnectionSettings)
- `src/backend/core/config/database.py` (canonical DSN builder)
- `src/backend/core/config/db_drivers.py` (реестр драйверов + fail-fast)
- `tools/check_dsn_drivers.py` (the check tool)
- `tools/check_dsn_drivers_allowlist.txt` (известный долг по объявлениям)
- `tests/unit/core/config/test_dsn_driver_availability.py`
- `tests/unit/tools/test_check_dsn_drivers_declarations.py`
