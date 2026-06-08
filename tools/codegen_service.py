"""Wave 5.1 — CLI для генерации service+repo+schema+action скелета.

S62 W3: мигрирован с ``argparse`` на ``typer`` + ``rich`` (libraries > custom,
per v22 п.5). Сохранены: typer-native entry ``app_main`` + legacy
``main()`` callback для backward-compat (sиmple argv parse).

Запуск::

    uv run python tools/codegen_service.py \\
        --name customers --domain core --crud --fields '{"first_name":"str","email":"str"}'

Создаёт:

* ``src/services/<domain>/<name>_service.py``  — сервис.
* ``src/infrastructure/repositories/<name>_repository.py`` — репозиторий.
* ``src/schemas/<name>.py`` — Pydantic-схемы.
* ``src/dsl/commands/<name>_actions.py`` — DSL-actions.

Не модифицирует существующие файлы (FileExistsError, если что-то уже есть).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from tools.codegen_engine import CodegenEngine

ROOT = Path(__file__).resolve().parents[1]

app = typer.Typer(
    name="codegen-service",
    help="Codegen service+repo+schema+action skeleton (Wave 5.1).",
    no_args_is_help=True,
    add_completion=False,
)
_console = Console()


def _to_pascal(name: str) -> str:
    """``customers`` → ``Customers``; ``order_items`` → ``OrderItems``."""
    return "".join(p.capitalize() for p in name.split("_"))


def _to_singular(name: str) -> str:
    """Грубая де-плюрализация: ``customers`` → ``customer``, ``boxes`` → ``box``."""
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses") or name.endswith("xes"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def _render_and_write(
    name: str,
    domain: str,
    crud: bool,
    fields: dict[str, str],
    model_class: str,
    overwrite: bool,
) -> None:
    """Render Jinja templates and write generated files (shared core)."""
    singular = _to_singular(name)
    pascal_singular = _to_pascal(singular)
    pascal_plural = _to_pascal(name)

    eng = CodegenEngine()
    paths = {
        "service": ROOT / "src" / "services" / domain / f"{name}_service.py",
        "repository": ROOT
        / "src"
        / "infrastructure"
        / "repositories"
        / f"{name}_repository.py",
        "schema": ROOT / "src" / "schemas" / f"{name}.py",
        "action": ROOT / "src" / "dsl" / "commands" / f"{name}_actions.py",
    }
    common: dict[str, Any] = {
        "name": name,
        "domain": domain,
        "entity": pascal_singular,
        "entity_short": singular,
        "class_name_short": pascal_singular,
        "model_class": model_class,
        "fields": fields,
    }
    for kind, target in paths.items():
        ctx: dict[str, Any] = {
            **common,
            "class_name": (
                f"{pascal_plural}Service"
                if kind == "service"
                else f"{pascal_plural}Repository"
                if kind == "repository"
                else f"{pascal_singular}Schemas"
            ),
            "crud": crud if kind == "service" else False,
        }
        template = f"{kind}.py.j2"
        code = eng.render(template, **ctx)
        eng.write(target, code, overwrite=overwrite)
        _console.print(f"[green][codegen][/green] wrote {target.relative_to(ROOT)}")

    _console.print(
        f"[bold green][codegen] OK[/bold green] {name} "
        f"(domain={domain}, crud={crud}, fields={list(fields)})"
    )


@app.command(name="generate")
def app_main(
    name: str = typer.Option(..., "--name", help="snake_case имя сервиса (мн.ч.)"),
    domain: str = typer.Option(..., "--domain", help="core | ai | integrations | ..."),
    crud: bool = typer.Option(False, "--crud", help="включить CRUD-методы"),
    fields: str = typer.Option(
        "{}", "--fields", help='JSON {"field":"py_type"} для Create/Update схем'
    ),
    model_class: str | None = typer.Option(
        None, "--model-class", help="имя SQLAlchemy-модели (default: PascalCase singular)"
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="разрешить перезапись существующих"
    ),
) -> None:
    """Typer-native entry point для codegen service skeleton."""
    parsed_fields = json.loads(fields) or {"name": "str"}
    _render_and_write(
        name=name,
        domain=domain,
        crud=crud,
        fields=parsed_fields,
        model_class=model_class or _to_pascal(_to_singular(name)),
        overwrite=overwrite,
    )


def main(argv: list[str] | None = None) -> int:
    """Backward-compat CLI entry (S58 W2 pattern).

    S62 W3: legacy argv parse делегирует в typer app для единой реализации.
    """
    if argv is None:
        argv = sys.argv[1:]
    try:
        app(args=argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
