"""Wave 5.3 → MINIMAX W6 P1-8 — CLI: SOAP/WSDL → actions.

Использует ``zeep`` (если установлен) для парсинга WSDL и извлечения
operation'ов. Каждая SOAP-операция превращается в ``action_id =
{connector}.{operation_name}``.

Запуск::

    uv run python tools/import_wsdl.py --url service.wsdl --connector myapi [--write]
    uv run python tools/import_wsdl.py --help  # auto-generated typer help

MINIMAX W6 P1-8 (cycle 152): мигрирован с ``argparse`` на ``typer`` +
``rich (libraries > custom, per ADR-0084). Сохранены: typer-native entry
``app_main`` + legacy ``main()`` callback для backward-compat.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]

app = typer.Typer(
    name="import-wsdl",
    help="WSDL → actions (Wave 5.3).",
    no_args_is_help=True,
    add_completion=False,
)
_console = Console()


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


@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    url: Optional[str] = typer.Option(None, "--url", help="URL или путь к WSDL"),
    connector: Optional[str] = typer.Option(None, "--connector", help="Имя коннектора"),
    write: bool = typer.Option(False, "--write", help="Записать generated actions"),
    output_dir: str = typer.Option(
        str(ROOT / "src" / "dsl" / "commands" / "imported"),
        "--output-dir",
        help="Директория для сгенерированных action-файлов",
    ),
) -> None:
    """WSDL → actions: извлекает операции и (опционально) генерирует файлы."""
    if ctx.invoked_subcommand is not None:
        return  # nested subcommand handle itself
    if url is None or connector is None:
        _console.print(
            "[bold red]Error:[/] --url и --connector обязательны для импорта."
        )
        raise typer.Exit(code=2)
    _run_wsdl_import(url=url, connector=connector, write=write, output_dir=output_dir)


def _run_wsdl_import(url: str, connector: str, write: bool, output_dir: str) -> None:
    """Внутренняя функция: extract WSDL operations + optional codegen."""
    operations = _collect_operations(url)
    _console.print(
        f"[bold cyan][import-wsdl][/] {connector}: {len(operations)} operations discovered"
    )
    for op in operations[:5]:
        _console.print(
            f"  • SOAP {op['operation_id']} → {connector}.{op['operation_id']}"
        )
    if len(operations) > 5:
        _console.print(f"  ... и ещё {len(operations) - 5}")

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
        code = _render_actions_module(connector, operations)
        eng.write(target, code, overwrite=True)
        _console.print(f"[bold green][import-wsdl][/] wrote {target.relative_to(ROOT)}")
    operations = _collect_operations(url)
    _console.print(
        f"[bold cyan][import-wsdl][/] {connector}: {len(operations)} operations discovered"
    )
    for op in operations[:5]:
        _console.print(
            f"  • SOAP {op['operation_id']} → {connector}.{op['operation_id']}"
        )
    if len(operations) > 5:
        _console.print(f"  ... и ещё {len(operations) - 5}")

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
        code = _render_actions_module(connector, operations)
        eng.write(target, code, overwrite=True)
        _console.print(f"[bold green][import-wsdl][/] wrote {target.relative_to(ROOT)}")


def main(argv: Optional[list[str]] = None) -> int:
    """Точка входа CLI (backward-compat shim для существующих скриптов).

    Запускает typer app через typer.testing.CliRunner (для тестов)
    или sys.argv (для CLI invocation). Возвращает exit code.
    """
    if argv is not None:
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    # CLI invocation: typer сам подхватит sys.argv[1:]
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())