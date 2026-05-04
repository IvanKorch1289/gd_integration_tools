"""Wave 5.3 — CLI: Postman v2.1 collection → actions.

Минимальный парсер Postman v2.1 collection: рекурсивно обходит ``items``,
извлекает ``request.method``, ``request.url.path`` и ``name`` →
конвертирует в action_id (snake_case).

Запуск::

    uv run python tools/import_postman.py --file collection.json --connector myapi [--write]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _flatten_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Рекурсивно собирает все request-items из nested folders."""
    result: list[dict[str, Any]] = []
    for item in items:
        if "request" in item:
            result.append(item)
        if "item" in item and isinstance(item["item"], list):
            result.extend(_flatten_items(item["item"]))
    return result


def _to_snake(text: str) -> str:
    """Превращает строку в snake_case operation id."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return s or "unknown_op"


def _collect_requests(collection: dict[str, Any]) -> list[dict[str, Any]]:
    """Извлекает (method, path, operation_id, summary) из коллекции."""
    items = _flatten_items(collection.get("item") or [])
    out: list[dict[str, Any]] = []
    for item in items:
        req = item.get("request") or {}
        method = (req.get("method") or "GET").upper()
        url = req.get("url")
        path = ""
        if isinstance(url, dict):
            parts = url.get("path") or []
            path = "/" + "/".join(parts) if parts else url.get("raw", "")
        elif isinstance(url, str):
            path = url
        name = item.get("name") or "request"
        out.append(
            {
                "method": method,
                "path": path,
                "operation_id": _to_snake(name),
                "summary": item.get("description") or name,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="Postman v2.1 → actions.")
    parser.add_argument("--file", required=True, help="Postman collection (.json)")
    parser.add_argument("--connector", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "src" / "dsl" / "commands" / "imported"),
    )
    args = parser.parse_args(argv)

    collection = json.loads(Path(args.file).read_text(encoding="utf-8"))
    requests = _collect_requests(collection)
    sys.stdout.write(
        f"[import-postman] {args.connector}: {len(requests)} requests discovered\n"
    )
    for r in requests[:5]:
        sys.stdout.write(
            f"  • {r['method']} {r['path']} → {args.connector}.{r['operation_id']}\n"
        )
    if len(requests) > 5:
        sys.stdout.write(f"  ... и ещё {len(requests) - 5}\n")

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
        code = _render_actions_module(args.connector, requests)
        eng.write(target, code, overwrite=True)
        sys.stdout.write(f"[import-postman] wrote {target.relative_to(ROOT)}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
