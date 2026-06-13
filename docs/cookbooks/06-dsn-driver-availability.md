# Cookbook 06: DSN Driver Availability

> Audience: devs configuring external databases (MSSQL, MySQL, DB2, Oracle).
> Time: 5-10 min.
> Difficulty: low.

## Problem

S104 W3 added support for **MSSQL**, **MySQL**, и **DB2** DSN types
(DEEP-RESEARCH D19). Драйверы для них — **optional dependencies**:

| DSN type | Sync driver | Async driver |
|----------|-------------|--------------|
| `postgresql` | `psycopg2` | `asyncpg` |
| `sqlite` | `sqlite3` (stdlib) | `aiosqlite` |
| `mssql` | `pyodbc` | `aioodbc` |
| `mysql` | `pymysql` | `aiomysql` |
| `db2` | `ibm_db_sa` | `ibm_db` |
| `oracle` | `cx_Oracle` | `oracledb` |

**Проблема:** если вы сконфигурировали `database.type=mssql` в `.env`,
но `pyodbc` не установлен в вашем venv, ошибка возникает только при
**runtime** (при попытке `DatabaseInitializer`), и сообщение obscure:
`ImportError: No module named 'pyodbc'`.

## Tool: `tools/check_dsn_drivers.py`

S106 W7 (B Sprint W2) добавил CI-runnable check tool, который заранее
определяет какие DSN types реально готовы в текущем venv.

### Human-readable режим

```bash
$ .venv/bin/python tools/check_dsn_drivers.py
DSN driver availability
============================================================
  postgresql   | sync=psycopg2     [MISS] | async=asyncpg      [OK ]
  sqlite       | sync=sqlite3      [OK ] | async=aiosqlite    [OK ]
  mssql        | sync=pyodbc       [MISS] | async=aioodbc      [MISS]
  mysql        | sync=pymysql      [MISS] | async=aiomysql     [MISS]
  db2          | sync=ibm_db_sa    [MISS] | async=ibm_db       [MISS]
  oracle       | sync=cx_Oracle    [MISS] | async=oracledb     [MISS]
============================================================
MISSING drivers — install via pip extras:
  pip install psycopg2
  pip install pyodbc
  pip install aioodbc
  ...
```

Exit 0 (no CI gate).

### CI режим

```bash
$ .venv/bin/python tools/check_dsn_drivers.py --ci
... (same output)
$ echo $?
1
```

Exit 1 если хотя бы один driver missing. Use в pre-deploy gate:
```bash
# In CI pipeline
python tools/check_dsn_drivers.py --ci || {
    echo "FATAL: missing DSN drivers. Run 'pip install ...' first."
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

### Project extras (if added to pyproject.toml)

If devs add `[project.optional-dependencies] databases = ["pyodbc", ...]`,
install via:
```bash
uv sync --extra databases
# or
pip install -e ".[databases]"
```

## Known caveats

- **`psycopg2`** — исторически C-extension, может требовать
  `libpq-dev` (Linux). Если не нужна sync PostgreSQL (asyncpg хватает
  для async-only use cases), можно пропустить.
- **`ibm_db`** — closed-source IBM драйвер, может быть недоступен на
  некоторых архитектурах. Fallback: `ibm_db_sa` (pure Python SQLAlchemy
  adapter) — НЕ async-friendly, но работает для sync.
- **`aioodbc`** — async обёртка над pyodbc, требует тот же system
  ODBC manager. Без `unixodbc-dev` на Linux `pip install aioodbc` упадёт.

## Related

- ADR-0192 (S106 closure, planned)
- `docs/migration/d5-models-to-core.md` (related: DSN parsing в DatabaseConnectionSettings)
- `src/backend/core/config/database.py` (canonical DSN builder)
- `tools/check_dsn_drivers.py` (the check tool)
- `tests/unit/tools/test_check_dsn_drivers.py` (7 tests)
