#!/usr/bin/env python3
"""AST-checker cross-layer imports для extensions/ (V15 GAP capability-gate).

S58 W2: мигрирован с ``argparse`` на ``typer`` + ``rich`` (libraries > custom
per v22 п.5 — "rich/typer/click не используются"). Сохранены:
* exit codes (0/1/2);
* TOML override;
* TYPE_CHECKING skip;
* поведение для CI / pre-commit (вызывается ``make lint:layer-imports``).

Если ``rich`` не установлен — fallback на plain text (для slim CI images).

Использование::

    python tools/check_layer_imports.py [<directory>] [--config PATH]
    python tools/check_layer_imports.py --help
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from pathlib import Path

# Дефолтные префиксы (V15 GAP, R3.10d). Override через --config / TOML.
DEFAULT_FORBIDDEN: tuple[str, ...] = (
    "src.backend.infrastructure.",
    "src.backend.services.",
)
DEFAULT_WHITELIST: tuple[str, ...] = ("src.backend.core.",)

# Имя файла с override'ом (если --config не указан ищем его рядом со скриптом).
DEFAULT_CONFIG_NAME = ".check_layer_imports.toml"


# === TOML parser (hand-rolled, без 3rd-party зависимости) ===


def _parse_toml(path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Читает TOML override. Возвращает (forbidden, whitelist).

    Без зависимости от tomllib/3rd-party: минимальный hand-rolled парсер
    секций ``[forbidden]`` / ``[whitelisted]`` с ключом ``prefixes = [...]``.
    Возвращает исходные DEFAULT_* при ошибке / отсутствии файла.
    """
    if not path.exists():
        return DEFAULT_FORBIDDEN, DEFAULT_WHITELIST
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_FORBIDDEN, DEFAULT_WHITELIST

    forbidden: list[str] = []
    whitelist: list[str] = []
    section: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" not in line or section not in {"forbidden", "whitelisted"}:
            continue
        key, value = (p.strip() for p in line.split("=", 1))
        if key != "prefixes":
            continue
        # Принимаем только list-литерал: ["a", "b"]
        if not (value.startswith("[") and value.endswith("]")):
            continue
        items = [p.strip().strip("\"'") for p in value[1:-1].split(",") if p.strip()]
        if section == "forbidden":
            forbidden.extend(items)
        else:
            whitelist.extend(items)
    return tuple(forbidden) or DEFAULT_FORBIDDEN, tuple(whitelist) or DEFAULT_WHITELIST


# === AST helpers (unchanged) ===


def _is_in_type_checking(tree: ast.AST, lineno: int) -> bool:
    """True если ``lineno`` находится внутри top-level ``if TYPE_CHECKING:``."""
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.If):
            continue
        if not _test_is_type_checking(node.test):
            continue
        end_lineno = node.end_lineno or node.lineno
        if node.lineno <= lineno <= end_lineno:
            return True
    return False


def _test_is_type_checking(test: ast.expr) -> bool:
    """Распознаёт ``TYPE_CHECKING`` в формах Name и Attribute."""
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if (
        isinstance(test, ast.Attribute)
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
        and test.attr == "TYPE_CHECKING"
    ):
        return True
    return False


def _iter_imports(tree: ast.AST) -> Iterable[tuple[str, int]]:
    """Yield (module, lineno) для каждого import / from-import."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module, node.lineno


def _scan_file(
    path: Path, forbidden: tuple[str, ...], whitelist: tuple[str, ...]
) -> list[tuple[int, str, str]]:
    """Возвращает список нарушений: (lineno, module, reason)."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return []

    violations: list[tuple[int, str, str]] = []
    for module, lineno in _iter_imports(tree):
        if _is_in_type_checking(tree, lineno):
            continue
        if module.startswith(whitelist):
            continue
        for prefix in forbidden:
            if module.startswith(prefix):
                violations.append((lineno, module, prefix))
                break
    return violations


def _walk_py_files(root: Path) -> Iterable[Path]:
    """Рекурсивно собирает ``.py`` файлы, пропуская ``__pycache__``."""
    for py in root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        yield py


# === Core scan logic (extracted for testability) ===


def scan_directory(
    root: Path,
    forbidden: tuple[str, ...] = DEFAULT_FORBIDDEN,
    whitelist: tuple[str, ...] = DEFAULT_WHITELIST,
) -> tuple[int, list[tuple[Path, int, str, str]]]:
    """Сканирует ``root`` на forbidden imports.

    Returns:
        (files_checked, violations) где violations = [(path, lineno, module, prefix)].
    """
    files_checked = 0
    all_violations: list[tuple[Path, int, str, str]] = []
    for py in _walk_py_files(root):
        files_checked += 1
        for lineno, module, prefix in _scan_file(py, forbidden, whitelist):
            all_violations.append((py, lineno, module, prefix))
    return files_checked, all_violations


# === Rich integration (lazy import + fallback) ===


def _try_import_console():
    """Lazy import rich.Console, returns None если rich не установлен."""
    try:
        from rich.console import Console  # type: ignore[import-not-found]

        return Console
    except ImportError:
        return None


def _try_import_table():
    """Lazy import rich.table.Table, returns None если rich не установлен."""
    try:
        from rich.table import Table  # type: ignore[import-not-found]

        return Table
    except ImportError:
        return None


# === Typer CLI app (NEW в S58 W2) ===

import typer  # noqa: E402

app = typer.Typer(
    name="check_layer_imports",
    help=(
        "AST-checker cross-layer imports в extensions/ (V15 GAP capability-gate). "
        "Запрещает прямой импорт src.backend.infrastructure.* и "
        "src.backend.services.* (default)."
    ),
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def main(
    directory: Path = typer.Argument(
        "extensions", help="Корень для обхода .py (default: extensions/)."
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help=f"Путь к .toml override (default: ищем {DEFAULT_CONFIG_NAME}).",
    ),
    plain: bool = typer.Option(
        False, "--plain", help="Disable rich output (для CI / non-TTY)."
    ),
) -> None:
    """AST-check cross-layer imports в extensions/."""
    Console = None if plain else _try_import_console()

    if not directory.exists():
        if Console:
            Console(stderr=True, style="red").print(
                f"ERROR: directory '{directory}' not found"
            )
        else:
            print(f"ERROR: directory '{directory}' not found", file=sys.stderr)
        raise typer.Exit(2)
    if not directory.is_dir():
        if Console:
            Console(stderr=True, style="red").print(
                f"ERROR: '{directory}' is not a directory"
            )
        else:
            print(f"ERROR: '{directory}' is not a directory", file=sys.stderr)
        raise typer.Exit(2)

    config_path = config or (Path.cwd() / DEFAULT_CONFIG_NAME)
    forbidden, whitelist = _parse_toml(config_path)

    files_checked, all_violations = scan_directory(directory, forbidden, whitelist)

    if not all_violations:
        msg = f"OK: {files_checked} files clean (forbidden={list(forbidden)})"
        if Console:
            Console().print(msg, style="green")
        else:
            print(msg)
        raise typer.Exit(0)

    sorted_violations = sorted(all_violations, key=lambda v: (str(v[0]), v[1]))

    if Console:
        # Rich table output
        Table = _try_import_table()
        console_err = Console(stderr=True)
        console_err.print(
            f"[bold red]ERROR: {len(all_violations)} forbidden import(s):[/bold red]"
        )
        if Table:
            table = Table(show_header=True, header_style="bold red")
            table.add_column("File", style="cyan")
            table.add_column("Line", style="yellow", justify="right")
            table.add_column("Import", style="red")
            table.add_column("Prefix", style="magenta")
            for py, lineno, module, prefix in sorted_violations:
                try:
                    rel = py.relative_to(directory)
                except ValueError:
                    rel = py
                table.add_row(str(rel), str(lineno), module, prefix)
            console_err.print(table)
    else:
        # Plain text fallback (для CI без rich)
        print(f"ERROR: {len(all_violations)} forbidden import(s):", file=sys.stderr)
        for py, lineno, module, prefix in sorted_violations:
            try:
                rel = py.relative_to(directory)
            except ValueError:
                rel = py
            print(
                f"  {rel}:{lineno}: forbidden import {module} (matches '{prefix}')",
                file=sys.stderr,
            )
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
