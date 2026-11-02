"""Shared SQL-валидация для DSL-процессоров (Wave 13 / Q13, аудит S-27).

Каноническая реализация правила «никаких multi-statement, DDL/PRIVILEGE и
файловых команд»: раньше копия этого паттерна жила в трёх местах
(``jdbc_query.py``, ``components/databasequeryprocessor.py`` и — после Wave 13 —
``infra_db.py``). Теперь реализация одна, а процессоры используют её через
``validate_sql``.

Запрещены:

* multi-statement (``;`` внутри запроса) — классический вектор «второго
  запроса» в обход строковых/параметрических фильтров;
* команды ``DROP``/``ALTER``/``TRUNCATE``/``CREATE``/``GRANT``/``REVOKE`` —
  изменение схемы и выдача прав на внутренней БД;
* файловые/загрузочные команды ``ATTACH``/``DETACH``/``COPY``/``INSTALL``/
  ``LOAD``/``EXPORT``/``IMPORT`` — DuckDB и PostgreSQL дают ФС-доступ прямо
  из SQL (``ATTACH`` подключает файл-БД, ``COPY ... FROM '/etc/passwd'``
  читает произвольный файл);
* вызовы файловых функций ``read_csv``/``read_csv_auto``/``read_parquet``/
  ``read_json``/``read_json_auto``/``glob`` — чтение произвольных файлов
  (DuckDB).

Запрещённые слова ищутся по всему тексту запроса (regex с word-boundary),
а не только как первое слово: ``SELECT read_csv('/etc/passwd')`` не
начинается с запрещённой команды, но читает ФС. Строковые литералы и
комментарии вырезаются перед проверкой — значение-строка
(``WHERE name = 'copy'``) не является SQL-командой.

Ограничение (ponytail): проверка лексическая, без парсинга SQL. Не ловятся:

* вложенные конструкции (``WITH ... AS (DELETE ...)``);
* команды, спрятанные в комментариях (комментарии вырезаются до проверки);
* динамические имена функций (вызов через переменную);
* неявное чтение файла (``FROM 'data.csv'`` в DuckDB).

Апгрейд (parse-уровень, read-only role в БД) — отдельная задача.

Классификация запроса (ADR-0382): ``sql_statement_kind`` возвращает
``"dml"`` / ``"read"`` / ``"unknown"`` по первой команде запроса, а
``needs_commit`` решает, нужна ли фиксация транзакции. Решение принимается
по **фактическому типу результата** (``result.returns_rows``), а не по первой
букве SQL: ``WITH ... SELECT`` — чтение, а ``INSERT ... RETURNING`` — DML,
который обязан быть зафиксирован.

ADR-0418: лимит выборки применяется **до** материализации результата —
``fetch_limited_rows`` забирает из курсора ``limit + 1`` строк
(``fetchmany``) вместо ``fetchall()``. «Лишняя» строка — маркер усечения
(``TRUNCATED_PROPERTY`` в ``Exchange.properties``).
"""

from __future__ import annotations

import inspect
import re
from typing import Any, Final

__all__ = (
    "FORBIDDEN_FUNCTIONS",
    "FORBIDDEN_SQL",
    "MAX_RESULT_ROWS",
    "TRUNCATED_PROPERTY",
    "db_capability_for_sql",
    "fetch_limited_rows",
    "limit_rows",
    "needs_commit",
    "result_returns_rows",
    "sql_capability_scope",
    "sql_statement_kind",
    "validate_sql",
)

#: Максимум строк, возвращаемых DSL-процессорами БД (ADR-0393).
#:
#: Раньше шаги делали ``fetchall()`` / ``mappings().all()`` без ограничения:
#: один ``SELECT * FROM big_table`` вытягивал в память процесса весь
#: результат — DoS через DSL-роут (и «съедание» памяти воркера).
MAX_RESULT_ROWS: int = 1000

#: Имя маркера усечения выборки в ``Exchange.properties`` (ADR-0418).
#:
#: Лимит теперь применяется **до** материализации результата, поэтому
#: «лишняя» строка не попадает в payload. Чтобы вызывающий знал, что
#: выборка обрезана, шаг выставляет этот флаг (``True``).
TRUNCATED_PROPERTY: str = "db_truncated"

#: SQL-команды, запрещённые для DSL-процессоров (DDL + privilege-management
#: + файловые/загрузочные команды).
FORBIDDEN_SQL: frozenset[str] = frozenset(
    {
        "DROP",
        "ALTER",
        "TRUNCATE",
        "CREATE",
        "GRANT",
        "REVOKE",
        # Файловые/загрузочные команды: DuckDB/PG дают ФС-доступ из SQL.
        "ATTACH",
        "DETACH",
        "COPY",
        "INSTALL",
        "LOAD",
        "EXPORT",
        "IMPORT",
    }
)

#: Файловые функции DuckDB/PostgreSQL — чтение произвольных файлов из SQL.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {"read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto", "glob"}
)

# Строковые литералы ('...', "...", `...`, $tag$...$tag$) — вырезаются
# перед проверкой: значение-строка не является SQL-командой.
_LITERAL_RE: Final = re.compile(
    r"'(?:[^']|'')*'"
    r'|"(?:[^"]|"")*"'
    r"|`(?:[^`])*`"
    r"|\$[A-Za-z_][A-Za-z0-9_]*\$.*?\$[A-Za-z_][A-Za-z0-9_]*\$"
    r"|\$\$.*?\$\$",
    re.DOTALL,
)
# Комментарии — тоже вырезаются (команда в комментарии не исполняется).
_COMMENT_RE: Final = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

# Запрещённые слова как отдельные токены (word-boundary), регистронезависимо.
_FORBIDDEN_TOKEN_RE: Final = re.compile(
    r"\b(?:"
    + "|".join(sorted(FORBIDDEN_SQL, key=lambda word: (-len(word), word)))
    + r")\b",
    re.IGNORECASE,
)
# Запрещённые файловые функции — только в форме вызова ``name(...)``.
_FORBIDDEN_FUNCTION_RE: Final = re.compile(
    r"\b(?:"
    + "|".join(sorted(FORBIDDEN_FUNCTIONS, key=lambda word: (-len(word), word)))
    + r")\s*\(",
    re.IGNORECASE,
)


def _sanitize(sql: str) -> str:
    """Убрать строковые литералы и комментарии из SQL.

    Args:
        sql: Исходный текст запроса.

    Returns:
        Текст запроса без литералов и комментариев (пробелы вместо них —
        чтобы соседние токены не склеивались).

    """
    return _COMMENT_RE.sub(" ", _LITERAL_RE.sub(" ", sql))


def validate_sql(sql: str) -> None:
    """Проверяет SQL: запрещает multi-statement, DDL/GRANT/REVOKE и ФС-доступ.

    Args:
        sql: Текст SQL-запроса.

    Raises:
        ValueError: Если запрос multi-statement, содержит запрещённую команду
            или вызов запрещённой файловой функции.

    """
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Multi-statement SQL is not allowed")
    sanitized = _sanitize(stripped)
    command = _FORBIDDEN_TOKEN_RE.search(sanitized)
    if command is not None:
        raise ValueError(f"SQL command '{command.group(0).upper()}' is not allowed")
    function = _FORBIDDEN_FUNCTION_RE.search(sanitized)
    if function is not None:
        raise ValueError(
            f"SQL function '{function.group(0).split('(')[0].lower()}' is not allowed"
        )


def db_capability_for_sql(sql: str) -> str:
    """Capability, требуемая для SQL-запроса (ADR-0393).

    Читающий запрос → ``db.read``; всё остальное (DML и неопознанные
    команды) → ``db.write``. Неопознанное трактуется как запись
    (fail-closed): подтверждённого чтения — меньше привилегий.

    Args:
        sql: Текст SQL-запроса.

    Returns:
        Имя capability (``"db.read"`` / ``"db.write"``).

    """
    return "db.read" if sql_statement_kind(sql) == "read" else "db.write"


def sql_capability_scope(sql: str) -> str | None:
    """Scope (алиас ресурса) для capability-запроса по SQL (ADR-0393).

    Scope = имя таблицы, к которой обращается запрос: capability
    ``db.read``/``db.write`` в модели ADR-044 использует
    :class:`ExactAliasMatcher` — scope совпадает с именем ресурса
    (``orders``, ``users``, ``files`` — те же алиасы, что объявляют
    плагины в ``plugin.toml``).

    Если запрос обращается к нескольким таблицам, scope не выводится
    (``None``): одна capability может нести только один scope, поэтому
    такой запрос fail-closed не пройдёт — разбивайте запрос на шаги.

    Args:
        sql: Текст SQL-запроса.

    Returns:
        Имя таблицы (алиас ресурса) либо ``None``.

    """
    from src.backend.core.tenancy.sqlalchemy_filter import referenced_tables

    tables = referenced_tables(sql)
    if len(tables) != 1:
        return None
    return next(iter(tables))


def limit_rows(
    rows: list[Any], *, limit: int = MAX_RESULT_ROWS
) -> tuple[list[Any], bool]:
    """Ограничить выборку по числу строк (ADR-0393).

    Args:
        rows: Полученные строки.
        limit: Максимум строк (``<= 0`` — без ограничения).

    Returns:
        Кортеж ``(строки, обрезано_ли)``.

    """
    if limit <= 0 or len(rows) <= limit:
        return rows, False
    return rows[:limit], True


async def _maybe_await(value: Any) -> Any:
    """Дождаться значения, если это awaitable (sync/async-результат).

    Args:
        value: Значение — обычное или coroutine/awaitable.

    Returns:
        Значение (для awaitable — результат ожидания).

    """
    if inspect.isawaitable(value):
        return await value
    return value


async def fetch_limited_rows(
    result: Any, *, limit: int = MAX_RESULT_ROWS
) -> tuple[list[Any], bool]:
    """Получить строки с лимитом, **не вытягивая весь результат** (ADR-0418).

    Лимит применяется к курсору: из результата забирается ``limit + 1``
    строк (``fetchmany``), а не весь результат (``fetchall``). «Лишняя»
    строка — маркер усечения: если вернулось ``limit + 1`` строк, значит
    в выборке есть ещё данные, и результат помечается усечённым (сама
    ``limit``-я строка в payload не попадает).

    До ADR-0418 лимит применялся **после** ``fetchall()`` — т.е. весь
    результат сначала оказывался в памяти процесса, и только потом
    обрезался. Один ``SELECT * FROM big_table`` = DoS по памяти.

    Args:
        result: Результат ``execute`` (sync ``CursorResult`` или async-аналог).
        limit: Максимум строк (``<= 0`` — без ограничения, весь результат).

    Returns:
        Кортеж ``(строки, усечено_ли)``.

    """
    if limit <= 0:
        rows = list(await _maybe_await(result.fetchall()))
        return rows, False
    fetched = await _maybe_await(result.fetchmany(limit + 1))
    return limit_rows(list(fetched), limit=limit)


#: SQL-команды, изменяющие данные (нужен ``commit``).
_DML_COMMANDS: Final = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "MERGE",
        "UPSERT",
        "REPLACE",
        "CALL",
        "EXEC",
        "EXECUTE",
    }
)

#: Read-only команды (commit не нужен).
_READ_COMMANDS: Final = frozenset(
    {
        "SELECT",
        "WITH",
        "VALUES",
        "TABLE",
        "SHOW",
        "DESCRIBE",
        "DESC",
        "EXPLAIN",
        "PRAGMA",
    }
)


def sql_statement_kind(sql: str) -> str:
    """Классифицирует SQL-запрос: ``"dml"`` / ``"read"`` / ``"unknown"``.

    Классификация — по первой команде запроса (комментарии и ведущие скобки
    отбрасываются). Нужна, чтобы отличить DML (нужен ``commit``) от чтения.

    Ограничение (ponytail): классификация лексическая, без парсинга SQL.
    Data-modifying CTE (``WITH x AS (INSERT ...) SELECT ...``) определяется как
    ``"read"`` — но ``needs_commit`` страхуется по фактическому типу результата.

    Args:
        sql: Текст SQL-запроса.

    Returns:
        ``"dml"`` — запрос меняет данные; ``"read"`` — только читает;
        ``"unknown"`` — не распознан.

    """
    sanitized = _COMMENT_RE.sub(" ", sql).strip()
    while sanitized.startswith("("):
        sanitized = sanitized[1:].lstrip()
    if not sanitized:
        return "unknown"
    token = sanitized.split(None, 1)[0].upper()
    if token in _DML_COMMANDS:
        return "dml"
    if token in _READ_COMMANDS:
        return "read"
    return "unknown"


def needs_commit(sql: str, *, returns_rows: bool) -> bool:
    """Нужен ли ``commit`` после выполнения запроса.

    Решение принимается по **фактическому типу результата**
    (``returns_rows``), а не по первой букве SQL: ``WITH ... SELECT`` — это
    чтение, а ``INSERT ... RETURNING`` — DML, который обязан быть зафиксирован.

    Args:
        sql: Текст выполненного SQL-запроса.
        returns_rows: ``result.returns_rows`` — возвращает ли результат строки.

    Returns:
        ``True``, если транзакцию нужно зафиксировать.

    """
    if sql_statement_kind(sql) == "dml":
        return True
    return not returns_rows


def result_returns_rows(result: Any, sql: str) -> bool:
    """Определяет, возвращает ли результат строки.

    Приоритет — фактический признак результата (``result.returns_rows``).
    Если атрибута нет (заглушка, не-SQLAlchemy result) — fallback на
    классификацию SQL: ``read`` → строки, ``dml`` → не возвращает.

    Args:
        result: Результат ``session.execute``.
        sql: Текст выполненного SQL-запроса.

    Returns:
        ``True``, если результат возвращает строки.

    """
    flag = getattr(result, "returns_rows", None)
    if isinstance(flag, bool):
        return flag
    return sql_statement_kind(sql) == "read"
