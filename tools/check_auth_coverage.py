#!/usr/bin/env python3
"""Линтер auth-покрытия endpoints (Wave [s2/k1-3-auth-guard], V7).

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

import argparse
import ast
import sys
from pathlib import Path

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
        self,
        file: Path,
        line: int,
        method: str,
        path: str,
        function: str,
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


def _is_router_decorator(node: ast.expr) -> tuple[str, str | None] | None:
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
    path: str | None = None
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
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
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
            assert isinstance(dec, ast.Call)
            if _has_auth_dependency(dec):
                continue
            findings.append(
                _Finding(file=file, line=dec.lineno, method=method, path=path,
                         function=node.name)
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default="src/backend/entrypoints/api",
        help="Корень поиска endpoint-файлов",
    )
    parser.add_argument(
        "--public-prefix",
        action="append",
        dest="public_prefixes",
        default=None,
        help="Префиксы публичных путей (можно повторять)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Выйти с кодом 1 при наличии нарушений (CI gate)",
    )
    args = parser.parse_args()
    prefixes = tuple(args.public_prefixes or DEFAULT_PUBLIC_PREFIXES)

    root = Path(args.root)
    if not root.exists():
        print(f"check_auth_coverage: путь {root} не существует", file=sys.stderr)
        return 1

    findings: list[_Finding] = []
    for file in sorted(root.rglob("*.py")):
        findings.extend(_scan_file(file, prefixes))

    if not findings:
        print(f"check_auth_coverage: OK (просканировано {root})")
        return 0

    print(
        f"check_auth_coverage: найдено {len(findings)} endpoint(ов) без "
        f"явной auth-зависимости:",
        file=sys.stderr,
    )
    for f in findings:
        print(f"  {f.format()}", file=sys.stderr)
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
