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
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ("FORBIDDEN_FUNCTIONS", "FORBIDDEN_SQL", "validate_sql")

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
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
        "glob",
    }
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
        raise ValueError(f"SQL function '{function.group(0).split('(')[0].lower()}' is not allowed")
