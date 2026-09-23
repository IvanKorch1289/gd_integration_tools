"""Wave 5.3 → MINIMAX W6 P1-8 Phase 2 — CLI: Postman v2.1 collection → actions.

Минимальный парсер Postman v2.1 collection: рекурсивно обходит ``items``,
извлекает ``request.method``, ``request.url.path`` и ``name`` →
конвертирует в action_id (snake_case).

Запуск::

    uv run python tools/import_postman.py --file collection.json --connector myapi [--write]
    uv run python tools/import_postman.py --help  # auto-generated typer help

MINIMAX W6 P1-8 Phase 2 (cycle 152): мигрирован с ``argparse`` на
``typer`` + ``rich`` (libraries > custom, per ADR-0084). Pattern из
ADR-0318 (Phase 1 pilot для import_wsdl.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]

app = typer.Typer(
    name="import-postman",
    help="Postman v2.1 → actions (Wave 5.3).",
    no_args_is_help=True,
    add_completion=False,
)
_console = Console()


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


@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    file: Optional[str] = typer.Option(None, "--file", help="Postman collection (.json)"),
    connector: Optional[str] = typer.Option(None, "--connector", help="Имя коннектора"),
    write: bool = typer.Option(False, "--write", help="Записать generated actions"),
    output_dir: str = typer.Option(
        str(ROOT / "src" / "dsl" / "commands" / "imported"),
        "--output-dir",
        help="Директория для сгенерированных action-файлов",
    ),
) -> None:
    """Postman v2.1 → actions: извлекает requests и (опционально) генерирует файлы."""
    if ctx.invoked_subcommand is not None:
        return  # nested subcommand handle itself
    if file is None or connector is None:
        _console.print(
            "[bold red]Error:[/] --file и --connector обязательны для импорта."
        )
        raise typer.Exit(code=2)
    _run_postman_import(file=file, connector=connector, write=write, output_dir=output_dir)


def _run_postman_import(
    file: str, connector: str, write: bool, output_dir: str
) -> None:
    """Внутренняя функция: extract Postman requests + optional codegen."""
    collection = json.loads(Path(file).read_text(encoding="utf-8"))
    requests = _collect_requests(collection)
    _console.print(
        f"[bold cyan][import-postman][/] {connector}: {len(requests)} requests discovered"
    )
    for r in requests[:5]:
        _console.print(
            f"  • {r['method']} {r['path']} → {connector}.{r['operation_id']}"
        )
    if len(requests) > 5:
        _console.print(f"  ... и ещё {len(requests) - 5}")

    if write:
        from tools.codegen_engine import CodegenEngine
        from tools.import_swagger import _render_actions_module

        eng = CodegenEngine()
        target = Path(output_dir) / f"{connector}_actions.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        init_path = target.parent / "__init__.py"
        if not init_path.exists():
            init_path.write_text(
                '"""Auto-generated actions modules (Wave 5.3)."""\n', encoding="utf-8"
            )
        code = _render_actions_module(connector, requests)
        eng.write(target, code, overwrite=True)
        _console.print(
            f"[bold green][import-postman][/] wrote {target.relative_to(ROOT)}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    """Точка входа CLI (backward-compat shim для существующих скриптов).

    Использует typer.testing.CliRunner (для тестов с явным argv) или
    app() (для CLI invocation через sys.argv).
    """
    if argv is not None:
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())