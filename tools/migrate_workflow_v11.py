"""Wave D.3 — Temporal-determinism validator для existing workflow-кода.

ADR-045: Temporal-определения требуют детерминированного кода
(никаких ``random.random()``, ``time.time()``, прямых IO в
``@workflow.defn``). Этот скрипт — **анализатор**, не auto-rewrite:
проходит AST файлов в ``src/workflows/`` и сообщает места, требующие
ручной правки при миграции на Temporal-backend.

Существующий ``OrderWorkflow`` (``src/workflows/orders_dsl.py``) ОСТАЁТСЯ
работать на ``PgRunnerWorkflowBackend`` (Wave D.1) до явной миграции.
Этот скрипт — pre-flight check для будущей Wave R3 / domain-плагина.

Что валидатор ловит:

* ``random.random()`` / ``random.randint()`` / ``uuid.uuid4()`` —
  заменить на ``workflow.random()`` / ``workflow.uuid4()``.
* ``time.time()`` / ``datetime.now()`` / ``datetime.utcnow()`` —
  заменить на ``workflow.now()``.
* ``asyncio.sleep`` — заменить на ``workflow.sleep`` /
  ``workflow.wait_condition``.
* Прямой ``import requests`` / ``import httpx`` / ``open(...)`` —
  переносить в Activity.
* ``threading`` / ``multiprocessing`` — запрещено.

Запуск::

    uv run python tools/migrate_workflow_v11.py src/workflows/
    uv run python tools/migrate_workflow_v11.py src/workflows/orders_dsl.py --json
    uv run python tools/migrate_workflow_v11.py src/workflows/ --strict  # exit 1 при findings
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

__all__ = ("Finding", "main", "scan_file")


@dataclass(slots=True, frozen=True)
class Finding:
    """Одна найденная проблема в коде workflow."""

    path: Path
    line: int
    col: int
    rule: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "line": self.line,
            "col": self.col,
            "rule": self.rule,
            "message": self.message,
        }


_NON_DETERMINISTIC_CALLS: dict[str, str] = {
    "random.random": "Use workflow.random().random() instead",
    "random.randint": "Use workflow.random().randint() instead",
    "random.choice": "Use workflow.random().choice() instead",
    "uuid.uuid4": "Use workflow.uuid4() instead",
    "uuid.uuid1": "Use workflow.uuid4() instead",
    "time.time": "Use workflow.now() instead",
    "time.monotonic": "Move to Activity (Workflow code is replay-deterministic)",
    "datetime.now": "Use workflow.now() instead",
    "datetime.utcnow": "Use workflow.now() instead",
    "asyncio.sleep": "Use workflow.sleep() / workflow.wait_condition() instead",
}

_FORBIDDEN_IMPORTS: dict[str, str] = {
    "threading": "Threading is not allowed in workflow code (replay-incompatible)",
    "multiprocessing": "Multiprocessing is not allowed in workflow code",
    "subprocess": "Subprocess is not allowed in workflow code (move to Activity)",
}

_IO_IMPORTS: dict[str, str] = {
    "requests": "HTTP I/O must be in Activity, not Workflow",
    "httpx": "HTTP I/O must be in Activity, not Workflow",
    "aiohttp": "HTTP I/O must be in Activity, not Workflow",
    "psycopg2": "DB I/O must be in Activity, not Workflow",
    "asyncpg": "DB I/O must be in Activity, not Workflow",
    "sqlalchemy": "DB I/O must be in Activity, not Workflow",
}


class _WorkflowVisitor(ast.NodeVisitor):
    """AST-обход с проверками non-determinism."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[Finding] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._check_import(alias.name, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module is not None:
            self._check_import(node.module, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        qualified = _qualified_name(node.func)
        if qualified in _NON_DETERMINISTIC_CALLS:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    col=node.col_offset,
                    rule="non-deterministic-call",
                    message=f"{qualified}(): {_NON_DETERMINISTIC_CALLS[qualified]}",
                )
            )
        self.generic_visit(node)

    def _check_import(self, module: str, node: ast.AST) -> None:
        root = module.split(".")[0]
        if root in _FORBIDDEN_IMPORTS:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=getattr(node, "lineno", 0),
                    col=getattr(node, "col_offset", 0),
                    rule="forbidden-import",
                    message=f"import {module}: {_FORBIDDEN_IMPORTS[root]}",
                )
            )
        elif root in _IO_IMPORTS:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=getattr(node, "lineno", 0),
                    col=getattr(node, "col_offset", 0),
                    rule="io-import",
                    message=f"import {module}: {_IO_IMPORTS[root]}",
                )
            )


def _qualified_name(node: ast.AST) -> str:
    """Восстановить ``module.attr`` имя из AST-узла."""
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        if prefix:
            return f"{prefix}.{node.attr}"
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def scan_file(path: Path) -> list[Finding]:
    """Анализ одного ``.py`` файла."""
    if not path.is_file() or path.suffix != ".py":
        return []
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Finding(
                path=path,
                line=exc.lineno or 0,
                col=exc.offset or 0,
                rule="syntax-error",
                message=str(exc.msg),
            )
        ]
    visitor = _WorkflowVisitor(path)
    visitor.visit(tree)
    return visitor.findings


def scan_paths(paths: Iterable[Path]) -> list[Finding]:
    """Рекурсивный обход директорий + файлов."""
    findings: list[Finding] = []
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*.py")):
                findings.extend(scan_file(child))
        else:
            findings.extend(scan_file(path))
    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point. Возвращает 0 / 1 в зависимости от ``--strict``."""
    parser = argparse.ArgumentParser(
        description="Validate workflow code for Temporal-determinism (ADR-045)."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Files or directories to scan",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON report",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any findings",
    )
    args = parser.parse_args(argv)

    findings = scan_paths(args.paths)
    if args.json:
        payload = {
            "summary": {
                "files_scanned": len({f.path for f in findings}),
                "findings": len(findings),
                "by_rule": _count_by_rule(findings),
            },
            "findings": [f.to_dict() for f in findings],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for f in findings:
            print(f"{f.path}:{f.line}:{f.col}: {f.rule}: {f.message}")
        print(
            f"\nTotal: {len(findings)} findings across "
            f"{len({f.path for f in findings})} files"
        )

    if args.strict and findings:
        return 1
    return 0


def _count_by_rule(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.rule] = counts.get(f.rule, 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
