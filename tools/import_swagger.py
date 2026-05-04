"""Wave 5.3 — CLI: Swagger/OpenAPI → ConnectorSpec + auto-actions + DSL-routes.

Читает OpenAPI 3.x спеку (JSON/YAML), извлекает все endpoint'ы и:

1. Печатает сводку: ``connector_name``, число endpoint'ов, action_id'ы.
2. (С ``--write``) создаёт файл
   ``src/dsl/commands/imported/<connector>_actions.py`` с
   :class:`ActionMetadata` + :class:`ActionHandlerSpec` для каждого
   endpoint'а; ``service_getter`` ссылается на лениво-создаваемый
   :class:`ImportedActionService` (см. ``services/integrations/imported_action_service.py``).

DoD: ``petstore.json`` (19 endpoints) → 19 actions без ручных правок.

Запуск::

    uv run python tools/import_swagger.py --url petstore.json --connector petstore [--write]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


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
            op_id = op.get("operationId") or _synth_op_id(method, path)
            endpoints.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": op_id,
                    "summary": op.get("summary") or "",
                }
            )
    return endpoints


def _synth_op_id(method: str, path: str) -> str:
    """Синтезирует operationId если его нет."""
    parts = [method.lower(), *(p for p in path.replace("{", "").replace("}", "").split("/") if p)]
    return "_".join(parts)


def _render_actions_module(connector: str, endpoints: list[dict[str, Any]]) -> str:
    """Рендерит Python-модуль с action_metadata + action_specs."""
    lines = [
        '"""Auto-generated from OpenAPI (Wave 5.3): connector ' + connector + '."""',
        "",
        "from __future__ import annotations",
        "",
        "from src.core.interfaces.action_dispatcher import ActionMetadata",
        "from src.dsl.commands.action_registry import ActionHandlerSpec",
        "",
        "__all__ = (",
    ]
    for ep in endpoints:
        action_id = f"{connector}.{ep['operation_id']}"
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


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="Swagger → actions (Wave 5.3).")
    parser.add_argument("--url", required=True, help="URL или путь к swagger.json/.yaml")
    parser.add_argument(
        "--connector", required=True, help="имя коннектора (snake_case)"
    )
    parser.add_argument(
        "--write", action="store_true", help="записать сгенерированный модуль"
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "src" / "dsl" / "commands" / "imported"),
        help="каталог для сгенерированного модуля",
    )
    args = parser.parse_args(argv)

    spec = _load_spec(args.url)
    endpoints = _collect_endpoints(spec)
    sys.stdout.write(
        f"[import-swagger] {args.connector}: {len(endpoints)} endpoints discovered\n"
    )
    for ep in endpoints[:5]:
        sys.stdout.write(
            f"  • {ep['method']} {ep['path']} → {args.connector}.{ep['operation_id']}\n"
        )
    if len(endpoints) > 5:
        sys.stdout.write(f"  ... и ещё {len(endpoints) - 5}\n")

    if args.write:
        from tools.codegen_engine import CodegenEngine

        eng = CodegenEngine()
        target = Path(args.output_dir) / f"{args.connector}_actions.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        # Авто-сгенерированный init для каталога imported/.
        init_path = target.parent / "__init__.py"
        if not init_path.exists():
            init_path.write_text(
                '"""Auto-generated actions modules (Wave 5.3)."""\n', encoding="utf-8"
            )
        code = _render_actions_module(args.connector, endpoints)
        eng.write(target, code, overwrite=True)
        sys.stdout.write(f"[import-swagger] wrote {target.relative_to(ROOT)}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
