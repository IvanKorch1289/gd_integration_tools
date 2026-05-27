"""S33 W4 — CLI: Swagger/OpenAPI → DSL connector actions.

Улучшения относительно Wave 5.3:
- Лучшая поддержка $ref (--resolve-refs)
- Multi-file output (--split)
- Route naming convention (snake_case нормализация operationId)

Запуск::

    # базовый режим (суммарная таблица endpoint'ов)
    uv run python tools/import_swagger.py --url petstore.json --connector petstore

    # с записью файлов
    uv run python tools/import_swagger.py --url petstore.json --connector petstore --write

    # с resolved $ref и split на отдельные action-файлы
    uv run python tools/import_swagger.py --url openapi.json --connector myapi \\
        --write --resolve-refs --split

    # verbose — показать все endpoints
    uv run python tools/import_swagger.py --url openapi.json --connector myapi --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _snake_case(name: str) -> str:
    """Normalize operationId / summary к snake_case."""
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name)
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"[^a-zA-Z0-9_]", "", name)
    return name.lower().strip("__")


def _load_spec(source: str) -> dict[str, Any]:
    """Читает OpenAPI-спеку из URL или локального файла (JSON/YAML)."""
    import json

    raw: bytes
    if source.startswith(("http://", "https://")):
        import httpx

        raw = httpx.get(source, timeout=30.0).content
    else:
        raw = Path(source).read_bytes()
    text = raw.decode("utf-8")
    if source.endswith((".yaml", ".yml")):
        import yaml

        return yaml.safe_load(text)
    return json.loads(text)


def _resolve_refs(spec: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно resolve all $ref в spec.

    Работает с $ref вида "#/components/schemas/Foo" — заменяет на
    actual schema definition из spec['components'].
    """
    import copy

    spec = copy.deepcopy(spec)

    def _resolve(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                ref_path = value["$ref"]
                if not ref_path.startswith("#/"):
                    return value
                parts = ref_path[2:].split("/")
                current: Any = spec
                for part in parts:
                    part_key = part.replace("~1", "/").replace("~0", "~")
                    if isinstance(current, dict) and part_key in current:
                        current = current[part_key]
                    else:
                        return value
                return _resolve(current)
            return {k: _resolve(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_resolve(item) for item in value]
        return value

    return _resolve(spec)


def _collect_endpoints(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Извлекает (method, path, operation_id, summary) из всех paths."""
    endpoints: list[dict[str, Any]] = []
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(op, dict):
                continue
            raw_op_id = op.get("operationId") or _synth_op_id(method, path)
            op_id = _snake_case(raw_op_id)
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": op_id,
                    "raw_operation_id": raw_op_id,
                    "summary": op.get("summary") or "",
                    "description": op.get("description") or "",
                    "schema": op.get("requestBodySchema") or op.get("requestBody"),
                }
            )
    return endpoints


def _synth_op_id(method: str, path: str) -> str:
    """Синтезирует operationId если его нет."""
    parts = [
        method.lower(),
        *(p for p in path.replace("{", "").replace("}", "").split("/") if p),
    ]
    return "_".join(parts)


def _render_actions_module(connector: str, endpoints: list[dict[str, Any]]) -> str:
    """Рендерит Python-модуль с ActionMetadata + ActionHandlerSpec."""
    lines = [
        f'"""Auto-generated OpenAPI connector "{connector}" (S33 W4)."""',
        "",
        "from __future__ import annotations",
        "",
        "from src.core.interfaces.action_dispatcher import ActionMetadata",
        "from src.dsl.commands.action_registry import ActionHandlerSpec",
        "",
        "__all__ = (",
    ]
    for ep in endpoints:
        lines.append(f"    {ep['operation_id']!r},")
    lines.extend((")", "", "_ALL_ACTIONS: dict[str, ActionMetadata] = {}", ""))

    for ep in endpoints:
        action_id = f"{connector}.{ep['operation_id']}"
        side_effect = "read" if ep["method"] == "GET" else "external"
        idempotent = ep["method"] in ("GET", "PUT", "DELETE")
        lines.extend(
            (
                f"{ep['operation_id']} = ActionMetadata(",
                f"    action={action_id!r},",
                f"    description={ep['summary']!r},",
                f"    side_effect={side_effect!r},",
                f"    idempotent={idempotent},",
                "    transports=('http',),",
                ")",
                f"_ALL_ACTIONS[{action_id!r}] = {ep['operation_id']}",
                "",
            )
        )

    return "\n".join(lines) + "\n"


def _render_single_action(connector: str, ep: dict[str, Any]) -> str:
    """Рендерит один action-файл (для --split режима)."""
    action_id = f"{connector}.{ep['operation_id']}"
    side_effect = "read" if ep["method"] == "GET" else "external"
    idempotent = ep["method"] in ("GET", "PUT", "DELETE")
    return f'''\
"""Action: {action_id} — {ep["summary"] or "(no description)"}."""

from __future__ import annotations

from src.core.interfaces.action_dispatcher import ActionMetadata

__all__ = ("{ep["operation_id"]}_metadata",)

{ep["operation_id"]}_metadata = ActionMetadata(
    action={action_id!r},
    description={ep["summary"]!r},
    side_effect={side_effect!r},
    idempotent={idempotent},
    transports=('http',),
)
'''


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="Swagger → actions (S33 W4).")
    parser.add_argument(
        "--url", required=True, help="URL или путь к swagger.json/.yaml"
    )
    parser.add_argument(
        "--connector", required=True, help="имя коннектора (snake_case)"
    )
    parser.add_argument("--write", action="store_true", help="записать результат")
    parser.add_argument(
        "--resolve-refs", action="store_true", help="resolve $ref перед обработкой"
    )
    parser.add_argument(
        "--split", action="store_true", help="разбить на отдельные action-файлы"
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "src" / "dsl" / "commands" / "imported"),
        help="каталог для результата",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="показать все endpoints (а не только первые 5)",
    )
    args = parser.parse_args(argv)

    spec = _load_spec(args.url)
    if args.resolve_refs:
        spec = _resolve_refs(spec)
    endpoints = _collect_endpoints(spec)

    sys.stdout.write(
        f"[import-swagger] {args.connector}: {len(endpoints)} endpoints discovered\n"
    )
    shown = endpoints if args.verbose else endpoints[:5]
    for ep in shown:
        sys.stdout.write(
            f"  • {ep['method']} {ep['path']} → {args.connector}.{ep['operation_id']}"
        )
        if ep["raw_operation_id"] != ep["operation_id"]:
            sys.stdout.write(f" (normalized from {ep['raw_operation_id']})")
        sys.stdout.write("\n")
    if not args.verbose and len(endpoints) > 5:
        sys.stdout.write(f"  ... (+ {len(endpoints) - 5} more, use --verbose)\n")

    if not args.write:
        return 0

    output_dir = Path(args.output_dir) / args.connector
    output_dir.mkdir(parents=True, exist_ok=True)

    # Ensure parent __init__.py exists
    init_path = output_dir.parent / "__init__.py"
    if not init_path.exists():
        init_path.write_text(
            '"""Auto-generated actions modules (S33 W4)."""\n', encoding="utf-8"
        )

    if args.split:
        (output_dir / "__init__.py").write_text(
            f'"""Actions for connector "{args.connector}" (S33 W4)."""\n'
            + "from __future__ import annotations\n"
            + "__all__ = ()\n",
            encoding="utf-8",
        )
        for ep in endpoints:
            action_file = output_dir / f"{ep['operation_id']}.py"
            action_file.write_text(
                _render_single_action(args.connector, ep), encoding="utf-8"
            )
        sys.stdout.write(
            f"[import-swagger] wrote {len(endpoints)} action files to {output_dir.relative_to(ROOT)}/\n"
        )
    else:
        target = output_dir / f"{args.connector}_actions.py"
        code = _render_actions_module(args.connector, endpoints)
        target.write_text(code, encoding="utf-8")
        sys.stdout.write(f"[import-swagger] wrote {target.relative_to(ROOT)}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
