"""Wave 5.5 — round-trip extract: Service-class → YAML.

Реверс-codegen: читает существующий ``services/<domain>/<name>_service.py``
через :mod:`libcst`, восстанавливает high-level YAML-описание сервиса.
Используется для миграции legacy-кода в codegen-модель и для проверки
``codegen_service.py`` идемпотентного round-trip.

Извлекает:

* Имя класса (``ClassDef.name``).
* Docstring класса (первый StringLiteral в body).
* Список public async-методов (имя + список параметров).

Запуск::

    uv run python tools/codegen_extract.py \\
        --service src/services/core/customers_service.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import libcst
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _extract_service(source: str) -> dict[str, Any]:
    """Достаёт описание сервис-класса из исходника через libcst."""
    module = libcst.parse_module(source)
    classes: list[dict[str, Any]] = []
    for node in module.body:
        if not isinstance(node, libcst.ClassDef):
            continue
        cls_dict: dict[str, Any] = {
            "name": node.name.value,
            "docstring": _extract_docstring(node.body),
            "methods": _extract_methods(node.body),
        }
        classes.append(cls_dict)
    return {"classes": classes}


def _extract_docstring(body: libcst.IndentedBlock | libcst.SimpleStatementSuite) -> str:
    """Возвращает docstring (первый StringLiteral или пустая строка)."""
    if not isinstance(body, libcst.IndentedBlock):
        return ""
    for stmt in body.body:
        if isinstance(stmt, libcst.SimpleStatementLine):
            for sub in stmt.body:
                if isinstance(sub, libcst.Expr) and isinstance(
                    sub.value, libcst.SimpleString
                ):
                    val = sub.value.evaluated_value
                    return val if isinstance(val, str) else val.decode("utf-8")
        break
    return ""


def _extract_methods(
    body: libcst.IndentedBlock | libcst.SimpleStatementSuite,
) -> list[dict[str, Any]]:
    """Список публичных async-методов с параметрами."""
    if not isinstance(body, libcst.IndentedBlock):
        return []
    methods: list[dict[str, Any]] = []
    for stmt in body.body:
        if not isinstance(stmt, libcst.FunctionDef):
            continue
        if stmt.name.value.startswith("_"):
            continue
        is_async = stmt.asynchronous is not None
        params = [
            p.name.value
            for p in stmt.params.params
            if p.name.value not in ("self", "cls")
        ]
        methods.append(
            {
                "name": stmt.name.value,
                "async": is_async,
                "params": params,
            }
        )
    return methods


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="Service → YAML (Wave 5.5).")
    parser.add_argument("--service", required=True, help="путь к service .py")
    parser.add_argument(
        "--output", default="-", help="путь YAML; '-' (default) — stdout"
    )
    args = parser.parse_args(argv)

    source = Path(args.service).read_text(encoding="utf-8")
    spec = _extract_service(source)
    text = yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)
    if args.output == "-":
        sys.stdout.write(text)
    else:
        Path(args.output).write_text(text, encoding="utf-8")
        sys.stdout.write(f"[extract] wrote {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
