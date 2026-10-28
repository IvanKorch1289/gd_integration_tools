"""DSN driver availability + declaration check (S106 W7 = Sprint B W2).

S104 W3 added MSSQL/MySQL/DB2 DSN types (DEEP-RESEARCH D19). Drivers
(``pyodbc``, ``aioodbc``, ``aiomysql``, ``pymysql``, ``ibm_db_sa``) are
**optional deps** — не в ``[project.dependencies]``, только в
``[project.optional-dependencies]`` (или вообще не включены в dev).

Проблема: если пользователь конфигурирует ``database.type=mssql`` без
``pyodbc``, ошибка возникает только при runtime ``DatabaseInitializer``
(и то через obscure ``ImportError``). Tool даёт fail-fast на этапе
bootstrap/CI.

Wave 13 Q9 добавляет вторую проверку — **декларативную**: драйвер,
упомянутый в DSN-конструкторе/настройках, должен быть объявлен хотя бы в
одном extra проекта (``[project.dependencies]`` или
``[project.optional-dependencies]``). Раньше ``psycopg2`` был дефолтом
sync-драйвера и не был объявлен нигде; ``pyodbc``/``ibm_db_sa``/``cx_Oracle``
— тоже. Известный долг вынесен в allowlist
(``tools/check_dsn_drivers_allowlist.txt``), новые gap'ы ломают CI.

Проверяет:
- Все DSN типы из ``DatabaseTypeChoices`` имеют соответствующий
  driver module (sync + async варианты)
- Driver actually importable в текущем venv
- Async + sync paired корректно (если async есть, sync должен быть)
- Драйверы из DSN-конструкторов объявлены в extras (allowlist для долга)

Запуск::

    python tools/check_dsn_drivers.py             # human-readable
    python tools/check_dsn_drivers.py --ci        # exit 1 на missing/gap
    python tools/check_dsn_drivers.py --ci --scope declarations
                                             # exit 1 только на необъявленные
                                             # драйверы (для CI: availability
                                             # требует установленных extras)

Exit code 0 — все drivers available и объявлены;
Exit code 1 — хотя бы один type requires missing driver или есть gap
в объявлении драйверов.

MINIMAX W6 P1-8 Phase 4 (cycle 153): мигрирован с ``argparse`` на ``typer`` +
``rich`` (libraries > custom, per ADR-0084). Сохранены: typer-native entry +
legacy ``main()`` callback для backward-compat с pre-existing scripts.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
import tomllib
from pathlib import Path
from typing import NamedTuple

import typer
from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.config.db_drivers import DB_DRIVER_DECLARATIONS  # noqa: E402

# S106 W7: маппинг DSN type → (sync_driver, async_driver) modules.
# Должно mirror то, что ``DatabaseConnectionSettings._build_dsn()`` использует
# (см. ``src/backend/core/config/database.py``).
DSN_DRIVER_MAP: dict[str, tuple[str, str]] = {
    "postgresql": ("psycopg", "asyncpg"),
    "sqlite": ("sqlite3", "aiosqlite"),
    "mssql": ("pyodbc", "aioodbc"),
    "mysql": ("pymysql", "aiomysql"),
    "db2": ("ibm_db_sa", "ibm_db"),  # ibm_db — async редкий, sync primary
    "oracle": ("oracledb", "oracledb"),
    # S121 W1: добавлен clickhouse (S168 W10 P1-8 — analytics path).
    # Sync driver: clickhouse-driver (official). Async: asynch.
    "clickhouse": ("clickhouse_driver", "asynch"),
}

#: Известные модули-драйверы БД. Используется как «вторая сеть» при
#: сканировании исходников конфигурации: любое упоминание такого имени
#: (например, в ``Field(examples=[...])``) проверяется на объявленность.
KNOWN_DRIVER_MODULES: frozenset[str] = frozenset(
    {
        "asyncpg",
        "psycopg",
        "psycopg2",
        "aiosqlite",
        "pysqlite",
        "sqlite3",
        "oracledb",
        "cx_Oracle",
        "aioodbc",
        "pyodbc",
        "aiomysql",
        "pymysql",
        "ibm_db",
        "ibm_db_sa",
        "clickhouse_connect",
        "clickhouse_driver",
        "asynch",
    }
)
#: Каталог исходников, где живут DSN-конструкторы и настройки драйверов.
CONFIG_SOURCES = Path("src") / "backend" / "core" / "config"

#: Allowlist известного долга (драйверы, которые упоминаются в коде,
#: но не объявлены ни в одном extra).
ALLOWLIST_FILE = Path("tools") / "check_dsn_drivers_allowlist.txt"

_REQUIREMENT_NAME_RE = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_DRIVER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class DriverCheckResult(NamedTuple):
    """Результат проверки одного DSN type."""

    db_type: str
    sync_driver: str
    async_driver: str
    sync_available: bool
    async_available: bool


class DeclarationGap(NamedTuple):
    """Драйвер упомянут в коде, но не объявлен в extras проекта.

    Attrs:
        driver: Имя модуля драйвера.
        location: ``путь:строка`` — место упоминания.
        detail: Человекочитаемое описание расхождения.
    """

    driver: str
    location: str
    detail: str

    def __str__(self) -> str:
        """Строковое представление gap'а для отчёта."""
        return f"{self.driver}: {self.location} — {self.detail}"


def _check_driver(module_name: str) -> bool:
    """Возвращает True если module importable."""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def check_all_drivers() -> list[DriverCheckResult]:
    """Проверить все DSN типы и вернуть список результатов."""
    results: list[DriverCheckResult] = []
    for db_type, (sync, async_) in DSN_DRIVER_MAP.items():
        results.append(
            DriverCheckResult(
                db_type=db_type,
                sync_driver=sync,
                async_driver=async_,
                sync_available=_check_driver(sync),
                async_available=_check_driver(async_),
            )
        )
    return results


def _normalize_distribution(name: str) -> str:
    """Нормализует имя дистрибутива (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def collect_declared_distributions(pyproject_path: Path) -> set[str]:
    """Собирает имена всех зависимостей, объявленных в ``pyproject.toml``.

    Учитываются и ``[project].dependencies``, и все extras из
    ``[project.optional-dependencies]``.

    Args:
        pyproject_path: Путь к ``pyproject.toml``.

    Returns:
        Множество нормализованных имён дистрибутивов.
    """
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    requirements: list[str] = list(project.get("dependencies", []))
    for extra_requirements in project.get("optional-dependencies", {}).values():
        requirements.extend(extra_requirements)

    declared: set[str] = set()
    for requirement in requirements:
        match = _REQUIREMENT_NAME_RE.match(requirement)
        if match:
            declared.add(_normalize_distribution(match.group(1)))
    return declared


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Возвращает id узлов, являющихся docstring'ами модуля/класса/функции."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def _iter_string_constants(tree: ast.AST) -> list[ast.Constant]:
    """Все строковые литералы дерева, кроме docstring'ов."""
    docstrings = _docstring_nodes(tree)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _is_driver_target(name: str) -> bool:
    """Похоже ли имя переменной/поля на имя драйвера."""
    return "driver" in name.lower()


def _collect_driver_literals(tree: ast.AST) -> set[str]:
    """Извлекает литералы-драйверы из AST конфигурационного модуля.

    Источники обещаний драйвера:
    * ``Field(default="psycopg")`` у полей ``async_driver``/``sync_driver``;
    * fallback-значения вида ``mssql_driver = driver or "pyodbc"``;
    * любой литерал из :data:`KNOWN_DRIVER_MODULES` (например, в
      ``Field(examples=[...])``).
    """
    drivers: set[str] = set()

    for node in ast.walk(tree):
        # Field(default="...") / присваивание драйвера строкой.
        if isinstance(node, ast.AnnAssign | ast.Assign):
            targets = (
                [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
            )
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not any(_is_driver_target(name) for name in names):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                drivers.add(value.value)
            elif isinstance(value, ast.Call):
                for keyword in value.keywords:
                    if keyword.arg == "default" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        if isinstance(keyword.value.value, str):
                            drivers.add(keyword.value.value)
            elif isinstance(value, ast.BoolOp | ast.IfExp):
                # Fallback-выражения вида `driver or ("aioodbc" if ... else ...)`.
                for constant in _iter_string_constants(value):
                    if _DRIVER_NAME_RE.match(constant.value):
                        drivers.add(constant.value)

    for constant in _iter_string_constants(tree):
        if constant.value in KNOWN_DRIVER_MODULES:
            drivers.add(constant.value)

    return drivers


def collect_driver_references(root: Path) -> dict[str, list[str]]:
    """Сканирует исходники конфигурации и собирает упоминания драйверов.

    Args:
        root: Корень сканирования (каталог с ``*.py``) или отдельный файл.

    Returns:
        Маппинг ``драйвер → список "путь:строка"``.
    """
    references: dict[str, list[str]] = {}
    files = [root] if root.is_file() else sorted(root.rglob("*.py"))
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        except SyntaxError:
            continue
        try:
            location = path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            location = path.as_posix()
        for driver in _collect_driver_literals(tree):
            for constant in _iter_string_constants(tree):
                if constant.value == driver:
                    references.setdefault(driver, []).append(
                        f"{location}:{constant.lineno}"
                    )
    return references


def load_allowlist(path: Path) -> frozenset[str]:
    """Читает allowlist известного долга (по одному имени драйвера в строке).

    Args:
        path: Путь к allowlist-файлу.

    Returns:
        Множество имён драйверов, скрытых из отчёта.
    """
    if not path.is_file():
        return frozenset()
    entries: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            entries.add(stripped)
    return frozenset(entries)


def check_driver_declarations(
    root: Path = PROJECT_ROOT, allowlist: frozenset[str] = frozenset()
) -> list[DeclarationGap]:
    """Проверяет, что все упомянутые драйверы объявлены в extras проекта.

    Args:
        root: Корень репозитория (где лежат ``pyproject.toml`` и исходники).
        allowlist: Драйверы известного долга — они не попадают в отчёт.

    Returns:
        Список расхождений (пустой список — всё объявлено).
    """
    pyproject_path = root / "pyproject.toml"
    has_manifest = pyproject_path.is_file()
    declared = collect_declared_distributions(pyproject_path) if has_manifest else set()
    references = collect_driver_references(root / CONFIG_SOURCES)

    gaps: list[DeclarationGap] = []

    # 1. Реестр проекта: дистрибутив-поставщик должен быть объявлен в extras.
    for driver, declaration in DB_DRIVER_DECLARATIONS.items():
        if declaration.extra == "stdlib" or not has_manifest:
            continue
        if _normalize_distribution(declaration.distribution) not in declared:
            gaps.append(
                DeclarationGap(
                    driver=driver,
                    location="core/config/db_drivers.py",
                    detail=(
                        f"дистрибутив '{declaration.distribution}' не объявлен "
                        f"в pyproject.toml (ожидался extra '{declaration.extra}')"
                    ),
                )
            )

    # 2. Упоминания в DSN-конструкторах: драйвер должен быть в реестре.
    for driver, locations in sorted(references.items()):
        if driver in DB_DRIVER_DECLARATIONS:
            continue
        for location in locations:
            gaps.append(
                DeclarationGap(
                    driver=driver,
                    location=location,
                    detail=(
                        "драйвер не объявлен ни в одном extra проекта "
                        "(секция project.optional-dependencies в pyproject.toml)"
                    ),
                )
            )

    return [gap for gap in gaps if gap.driver not in allowlist]


def render_declarations(gaps: list[DeclarationGap]) -> str:
    """Human-readable отчёт по расхождениям в объявлении драйверов."""
    lines = ["DSN driver declarations", "=" * 60]
    if gaps:
        lines.append("UNDECLARED drivers — упомянуты в коде, но не в extras:")
        for gap in gaps:
            lines.append(f"  {gap.driver:12s} | {gap.location} | {gap.detail}")
    else:
        lines.append("All referenced drivers are declared in extras.")
    return "\n".join(lines)


def render_human(results: list[DriverCheckResult]) -> str:
    """Human-readable report."""
    lines = ["DSN driver availability", "=" * 60]
    for r in results:
        sync_marker = "OK " if r.sync_available else "MISS"
        async_marker = "OK " if r.async_available else "MISS"
        lines.append(
            f"  {r.db_type:12s} | sync={r.sync_driver:12s} [{sync_marker}] | "
            f"async={r.async_driver:12s} [{async_marker}]"
        )
    lines.append("=" * 60)
    missing = [r for r in results if not r.sync_available or not r.async_available]
    if missing:
        lines.append("MISSING drivers — install via pip extras:")
        seen: set[str] = set()
        for r in missing:
            if not r.sync_available and r.sync_driver not in seen:
                lines.append(f"  pip install {r.sync_driver}")
                seen.add(r.sync_driver)
            if not r.async_available and r.async_driver not in seen:
                lines.append(f"  pip install {r.async_driver}")
                seen.add(r.async_driver)
    else:
        lines.append("All drivers available — all DSN types ready.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI (backward-compat shim для существующих скриптов).

    Запускает typer app через typer.testing.CliRunner (для тестов)
    или sys.argv (для CLI invocation). Возвращает exit code.
    """
    if argv is not None:
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    # CLI invocation: typer сам подхватит sys.argv[1:]
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


app = typer.Typer(
    name="check-dsn-drivers",
    help="DSN driver availability check (sync + async).",
    add_completion=False,
)
_console = Console()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    ci: bool = typer.Option(
        False,
        "--ci",
        help="Exit code 1 on missing drivers (for CI gates).",
    ),
    scope: str = typer.Option(
        "all",
        "--scope",
        help=(
            "Что считать блокирующим при --ci: declarations (только необъявленные "
            "драйверы — блокирует CI), availability (наличие драйверов в venv — "
            "требует установленных extras, не блокирует), all (по умолчанию)."
        ),
    ),
) -> None:
    """Точка входа: human-readable или CI mode."""
    if ctx.invoked_subcommand is not None:
        return

    results = check_all_drivers()
    _console.print(render_human(results))

    allowlist = load_allowlist(PROJECT_ROOT / ALLOWLIST_FILE)
    gaps = check_driver_declarations(PROJECT_ROOT, allowlist)
    _console.print(render_declarations(gaps))

    if ci:
        missing = [r for r in results if not r.sync_available or not r.async_available]
        if scope not in ("declarations", "availability", "all"):
            _console.print(
                f"[red]Неизвестный scope: {scope} "
                "(допустимо: declarations | availability | all)[/red]"
            )
            raise typer.Exit(code=2)
        fail_declarations = scope in ("declarations", "all") and bool(gaps)
        fail_availability = scope in ("availability", "all") and bool(missing)
        if fail_declarations or fail_availability:
            raise typer.Exit(code=1)


if __name__ == "__main__":
    raise SystemExit(main())
