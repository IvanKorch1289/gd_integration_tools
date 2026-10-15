"""Scaffold sub-app для ``manage.py``.

P1 CLI decomposition W5 (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability. ``scaffold`` — Typer sub-app с 5 subcommands
для code generation (service/processor/route/codegen-service/codegen-extract).

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py scaffold service <name>`` — Service + Schema + Actions.
- ``python manage.py scaffold processor <name>`` — DSL processor.
- ``python manage.py scaffold route <name> --source <source>`` — DSL route YAML.
- ``python manage.py scaffold codegen-service --name <n> --domain <d> [--crud] [--fields ...]`` — фасад tools/codegen_service.
- ``python manage.py scaffold codegen-extract --service <path> [--output <yaml>]`` — фасад tools/codegen_extract.

Typer sub-app pattern (отличается от W1+W3+W4):
- ``scaffold_app = typer.Typer(help="Генерация кода")``
- ``app.add_typer(scaffold_app, name="scaffold")`` в manage.py
- Команды регистрируются через ``@scaffold_app.command("name")``
"""

from __future__ import annotations

from pathlib import Path

import typer

scaffold_app = typer.Typer(help="Генерация кода")


@scaffold_app.command("service")
def scaffold_service(name: str) -> None:
    """Генерация Service + Schema + Actions."""
    base = Path("src")
    service_file = base / "services" / f"{name}.py"
    if service_file.exists():
        typer.echo(f"Service {name} already exists!", err=True)
        raise typer.Exit(1)

    class_name = name.capitalize() + "Service"
    content = f'''"""Сервис {name} — автогенерация через manage.py scaffold."""

from src.backend.infrastructure.decorators.singleton import singleton

__all__ = ("{class_name}", "get_{name}_service")


@singleton
class {class_name}:
    async def get_all(self) -> list:
        return []

    async def get_by_id(self, id: int):
        return None

    async def create(self, data: dict):
        return data

    async def update(self, id: int, data: dict):
        return data

    async def delete(self, id: int) -> bool:
        return True


def get_{name}_service() -> {class_name}:
    return {class_name}()
'''
    service_file.write_text(content)
    typer.echo(f"Created: {service_file}")
    typer.echo(
        "Next: register in src/core/service_setup.py and src/dsl/commands/setup.py"
    )


@scaffold_app.command("processor")
def scaffold_processor(name: str) -> None:
    """Генерация DSL processor.

    2026-10-15: шаблон берётся из :func:`tools.scaffold.processor_template` —
    единый источник истины. Раньше CLI держал собственную копию с
    ``# TODO: implement processor logic``, то есть генерировал no-op процессор
    (тот же дефект был починен в tools/scaffold.py коммитом a053f722e).
    """
    from tools.scaffold import processor_template

    class_name = "".join(w.capitalize() for w in name.split("_"))
    file_path = Path("src/backend/dsl/engine/processors") / f"{name}.py"
    if file_path.exists():
        typer.echo(f"Processor {name} already exists!", err=True)
        raise typer.Exit(1)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(processor_template(class_name), encoding="utf-8")
    typer.echo(f"Created: {file_path}")
    typer.echo("Next: add to processors/__init__.py and builder.py")


@scaffold_app.command("route")
def scaffold_route(name: str, source: str = "internal") -> None:
    """Генерация DSL route YAML.

    2026-10-15: путь изменён с legacy ``dsl_routes/`` на ``routes/<name>/``
    (R-V15-2 — DSL-routes являются «лёгкими плагинами» с манифестом
    ``route.toml``). Формат шага приведён к актуальному контракту
    ``steps:[]`` (V15 universal route formula).
    """
    route_dir = Path("routes") / name
    file_path = route_dir / f"{name}.dsl.yaml"
    if file_path.exists():
        typer.echo(f"Route {name} already exists!", err=True)
        raise typer.Exit(1)

    content = f"""# Маршрут {name} — сгенерирован manage.py scaffold.
# Manifest: routes/{name}/route.toml (name, version, capabilities).
# route_id можно опустить — RouteLoader подставит имя из манифеста.
route_id: {name}
from: "{source}:{name}"
description: "Auto-generated route for {name}"
steps:
  - log: {{ level: info }}
  - transform:
      expression: "body"
      to: "body"
  # TODO: добавьте шаги: proxy / call_function / dispatch_action / ...
"""
    route_dir.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    typer.echo(f"Created: {file_path}")
    typer.echo(f"Next: create routes/{name}/route.toml (manifest + capabilities)")


@scaffold_app.command("codegen-service")
def scaffold_codegen_service(
    name: str = typer.Option(..., help="snake_case имя сервиса (мн.ч.)"),
    domain: str = typer.Option(..., help="core | ai | integrations | ..."),
    crud: bool = typer.Option(False, "--crud/--no-crud", help="включить CRUD-методы"),
    fields: str = typer.Option(
        "{}", help='JSON {"field":"py_type"} для Create/Update схем'
    ),
    model_class: str | None = typer.Option(
        None,
        "--model-class",
        help="имя SQLAlchemy-модели (default: PascalCase singular)",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="разрешить перезапись"),
) -> None:
    """Wave 5.1 — фасад над `tools/codegen_service.py` через Typer."""
    from tools.codegen_service import main as _codegen_main

    argv: list[str] = ["--name", name, "--domain", domain, "--fields", fields]
    if crud:
        argv.append("--crud")
    if model_class is not None:
        argv.extend(["--model-class", model_class])
    if overwrite:
        argv.append("--overwrite")
    raise typer.Exit(_codegen_main(argv))


@scaffold_app.command("codegen-extract")
def scaffold_codegen_extract(
    service: str = typer.Option(..., help="путь к service .py"),
    output: str = typer.Option("-", help="путь YAML; '-' (default) — stdout"),
) -> None:
    """Wave 5.5 — фасад над `tools/codegen_extract.py` через Typer."""
    from tools.codegen_extract import main as _extract_main

    raise typer.Exit(_extract_main(["--service", service, "--output", output]))


__all__ = ("scaffold_app",)
