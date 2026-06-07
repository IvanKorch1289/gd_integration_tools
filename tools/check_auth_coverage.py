#!/usr/bin/env python3
"""Линтер auth-покрытия endpoints (Wave [s2/k1-3-auth-guard], V7).

S59 W1 (libraries > custom, v22 п.5): мигрирован с ``argparse`` на
``typer`` + ``rich``.

Гарантирует, что каждый ``@router.<method>`` в ``entrypoints/api/v1/endpoints/``
либо:
1. имеет explicit ``dependencies=[Depends(require_auth(...))]``,
2. либо его путь матчится одному из ``--public-prefix``
   (allowlist публичных путей).

V7 defense-in-depth: даже если разработчик забыл require_auth,
:class:`AuthRequiredMiddleware` блокирует запрос. Этот линтер
гарантирует, что **разработчик** явно описывает auth-намерение
вместо неявной зависимости от middleware.

Запуск::

    python tools/check_auth_coverage.py [--strict] [--root SRC] [--public-prefix /health ...]

Поведение:
* без ``--strict``: выводит warning список, exit 0;
* со ``--strict``: при наличии нарушений exit 1 (CI gate).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

ROUTER_DECORATOR_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)
REQUIRE_AUTH_NAMES = frozenset(
    {"require_auth", "require_api_key", "require_admin", "verify_admin"}
)
DEFAULT_PUBLIC_PREFIXES = (
    "/health",
    "/healthz",
    "/readyz",
    "/livez",
    "/metrics",
    "/asyncapi",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class _Finding:
    __slots__ = ("file", "line", "method", "path", "function")

    def __init__(
        self, file: Path, line: int, method: str, path: str, function: str
    ) -> None:
        self.file = file
        self.line = line
        self.method = method
        self.path = path
        self.function = function

    def format(self) -> str:
        return (
            f"{self.file}:{self.line} {self.method.upper()} {self.path} "
            f"(handler={self.function})"
        )


def _is_router_decorator(node: ast.expr) -> Optional[tuple[str, Optional[str]]]:
    """Возвращает (method, path) если ``node`` это ``@router.<method>(...)``.

    ``path`` извлекается из позиционного аргумента (строковая константа).
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name):
        return None
    if func.value.id not in {"router", "app"}:
        return None
    method = func.attr.lower()
    if method not in ROUTER_DECORATOR_METHODS:
        return None
    path: Optional[str] = None
    if node.args and isinstance(node.args[0], ast.Constant):
        if isinstance(node.args[0].value, str):
            path = node.args[0].value
    return method, path


def _has_auth_dependency(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg != "dependencies":
            continue
        if not isinstance(kw.value, (ast.List, ast.Tuple)):
            continue
        for elt in kw.value.elts:
            if _expr_mentions_auth(elt):
                return True
    return False


def _expr_mentions_auth(expr: ast.expr) -> bool:
    """True если AST-выражение упоминает один из ``REQUIRE_AUTH_NAMES``."""
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Name) and sub.id in REQUIRE_AUTH_NAMES:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in REQUIRE_AUTH_NAMES:
            return True
    return False


def _path_is_public(path: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _scan_file(file: Path, prefixes: tuple[str, ...]) -> list[_Finding]:
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    findings: list[_Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            match = _is_router_decorator(dec)
            if match is None:
                continue
            method, path = match
            if path is None:
                continue
            if _path_is_public(path, prefixes):
                continue
            assert isinstance(dec, ast.Call)  # noqa: S101
            if _has_auth_dependency(dec):
                continue
            findings.append(
                _Finding(
                    file=file,
                    line=dec.lineno,
                    method=method,
                    path=path,
                    function=node.name,
                )
            )
    return findings


app = typer.Typer(
    name="check_auth_coverage",
    help="Auth coverage linter: каждый endpoint либо явно auth-protected, либо public-allowlisted.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
console_err = Console(stderr=True, style="red")


@app.command()
def main(
    root: str = typer.Option(
        "src/backend/entrypoints/api",
        "--root",
        help="Корень поиска endpoint-файлов",
    ),
    public_prefix: Optional[list[str]] = typer.Option(
        None,
        "--public-prefix",
        help="Префиксы публичных путей (можно повторять)",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Выйти с кодом 1 при наличии нарушений (CI gate)",
    ),
) -> None:
    """CLI-entrypoint (typer)."""
    # Typer Optional[list] parameter: when no flag passed, value is OptionInfo
    # (truthy, не None, не iterable). Treat OptionInfo as "no value".
    if public_prefix is None or not isinstance(public_prefix, list):
        prefixes: tuple[str, ...] = DEFAULT_PUBLIC_PREFIXES
    else:
        prefixes = tuple(public_prefix)

    root_path = Path(root)
    if not root_path.exists():
        console_err.print(f"[red]check_auth_coverage: путь {root_path} не существует[/red]")
        raise typer.Exit(1)

    findings: list[_Finding] = []
    for file in sorted(root_path.rglob("*.py")):
        findings.extend(_scan_file(file, prefixes))

    if not findings:
        console.print(
            f"[bold green]✓[/bold green] check_auth_coverage: OK (просканировано {root_path})"
        )
        raise typer.Exit(0)

    console_err.print(
        f"[bold red]✗ check_auth_coverage: найдено {len(findings)} endpoint(ов) "
        f"без явной auth-зависимости:[/bold red]"
    )
    table = Table(show_header=True, header_style="bold red")
    table.add_column("File", style="cyan")
    table.add_column("Line", style="yellow", justify="right")
    table.add_column("Method", style="magenta")
    table.add_column("Path", style="red")
    table.add_column("Handler", style="green")
    for f in findings:
        table.add_row(str(f.file), str(f.line), f.method.upper(), f.path, f.function)
    console_err.print(table)
    raise typer.Exit(1 if strict else 0)


if __name__ == "__main__":
    app()
