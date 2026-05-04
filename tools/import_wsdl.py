"""Wave 5.3 — CLI: SOAP/WSDL → actions.

Использует ``zeep`` (если установлен) для парсинга WSDL и извлечения
operation'ов. Каждая SOAP-операция превращается в ``action_id =
{connector}.{operation_name}``.

Запуск::

    uv run python tools/import_wsdl.py --url service.wsdl --connector myapi [--write]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _collect_operations(wsdl_url: str) -> list[dict[str, Any]]:
    """Извлекает SOAP-операции через ``zeep``."""
    try:
        from zeep import Client
    except ImportError as exc:
        raise RuntimeError(
            "zeep не установлен — добавьте `zeep` в зависимости проекта "
            "(или используйте --skip-parse для dry-run)"
        ) from exc

    client = Client(wsdl_url)
    operations: list[dict[str, Any]] = []
    for service in client.wsdl.services.values():
        for port in service.ports.values():
            for op_name, op in port.binding._operations.items():
                operations.append(
                    {
                        "method": "POST",
                        "path": str(port.binding_options.get("address", "")),
                        "operation_id": op_name,
                        "summary": getattr(op, "documentation", "") or "",
                    }
                )
    return operations


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="WSDL → actions (Wave 5.3).")
    parser.add_argument("--url", required=True, help="URL или путь к WSDL")
    parser.add_argument("--connector", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "src" / "dsl" / "commands" / "imported"),
    )
    args = parser.parse_args(argv)

    operations = _collect_operations(args.url)
    sys.stdout.write(
        f"[import-wsdl] {args.connector}: {len(operations)} operations discovered\n"
    )
    for op in operations[:5]:
        sys.stdout.write(
            f"  • SOAP {op['operation_id']} → {args.connector}.{op['operation_id']}\n"
        )
    if len(operations) > 5:
        sys.stdout.write(f"  ... и ещё {len(operations) - 5}\n")

    if args.write:
        from tools.codegen_engine import CodegenEngine
        from tools.import_swagger import _render_actions_module

        eng = CodegenEngine()
        target = Path(args.output_dir) / f"{args.connector}_actions.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        init_path = target.parent / "__init__.py"
        if not init_path.exists():
            init_path.write_text(
                '"""Auto-generated actions modules (Wave 5.3)."""\n', encoding="utf-8"
            )
        code = _render_actions_module(args.connector, operations)
        eng.write(target, code, overwrite=True)
        sys.stdout.write(f"[import-wsdl] wrote {target.relative_to(ROOT)}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
