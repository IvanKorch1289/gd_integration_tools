#!/usr/bin/env python3
"""GD Integration Tools — CLI для управления проектом.

Замена manage.sh: запуск backend/frontend, миграции, scaffolding, introspection.

Usage:
    python manage.py run              # Backend (uvicorn)
    python manage.py run-frontend     # Streamlit dashboard
    python manage.py run-all          # Backend + Frontend параллельно
    python manage.py migrate          # Alembic migrations
    python manage.py routes           # Список DSL routes
    python manage.py actions          # Список actions
    python manage.py scaffold service invoices  # Генерация сервиса
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer(
    name="gd-tools", help="GD Integration Tools — management CLI", add_completion=True
)


# ────────────── Runtime ──────────────


@app.command()
def run(
    host: str | None = typer.Option(None, help="Bind host (override APP_HOST)"),
    port: int | None = typer.Option(None, help="Bind port (override APP_PORT)"),
    workers: int | None = typer.Option(
        None, help="Worker count (override APP_WORKERS)"
    ),
    server: str | None = typer.Option(
        None, help="ASGI server: uvicorn | granian (override APP_SERVER)"
    ),
):
    """Запуск FastAPI backend через выбранный ASGI-сервер.

    Делегирует выбор бэкенда (uvicorn/granian) в ``src.main:run`` —
    управляется ``settings.app.server`` (env ``APP_SERVER``).
    """
    if host is not None:
        os.environ["APP_HOST"] = host
    if port is not None:
        os.environ["APP_PORT"] = str(port)
    if workers is not None:
        os.environ["APP_WORKERS"] = str(workers)
    if server is not None:
        os.environ["APP_SERVER"] = server

    cmd = [sys.executable, "-m", "src.main"]
    typer.echo(
        f"Starting backend (server={os.environ.get('APP_SERVER', 'uvicorn')})..."
    )
    os.execvp(cmd[0], cmd)


@app.command("run-frontend")
def run_frontend(port: int = typer.Option(8501, help="Streamlit port")):
    """Запуск Streamlit dashboard."""
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "src/entrypoints/streamlit_app/app.py",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]
    typer.echo(f"Starting Streamlit on :{port}...")
    os.execvp(cmd[0], cmd)


@app.command("run-all")
def run_all(
    backend_port: int = typer.Option(8000, help="Backend port"),
    frontend_port: int = typer.Option(8501, help="Frontend port"),
):
    """Запуск backend + frontend параллельно."""
    procs: list[subprocess.Popen] = []

    try:
        typer.echo(
            f"Starting backend on :{backend_port} + frontend on :{frontend_port}..."
        )

        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(backend_port),
            ]
        )
        procs.append(backend)

        frontend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "src/entrypoints/streamlit_app/app.py",
                "--server.port",
                str(frontend_port),
                "--server.headless",
                "true",
            ]
        )
        procs.append(frontend)

        typer.echo("Both services running. Press Ctrl+C to stop.")
        for p in procs:
            p.wait()

    except KeyboardInterrupt:
        typer.echo("\nStopping services...")
        for p in procs:
            p.send_signal(signal.SIGTERM)
        for p in procs:
            p.wait(timeout=10)
        typer.echo("Services stopped.")


# ────────────── Database ──────────────


@app.command()
def migrate():
    """Применить все накопившиеся миграции (alembic upgrade head)."""
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    typer.echo("Migrations applied.")


@app.command("makemigration")
def make_migration(
    message: str = typer.Argument(
        ..., help="Описание миграции (станет частью имени файла)"
    ),
    autogenerate: bool = typer.Option(
        True,
        "--autogenerate/--empty",
        help="Авто-детект изменений моделей (по умолчанию) или создать пустую миграцию",
    ),
):
    """Создать новую alembic-миграцию.

    Примеры::

        uv run python manage.py makemigration "add orders table"
        uv run python manage.py makemigration "manual data backfill" --empty
    """
    cmd = [sys.executable, "-m", "alembic", "revision"]
    if autogenerate:
        cmd.append("--autogenerate")
    cmd.extend(["-m", message])
    subprocess.run(cmd, check=True)
    typer.echo(
        "Migration created. Проверь сгенерированный файл в "
        "src/infrastructure/database/migrations/versions/ перед `migrate`."
    )


@app.command("downgrade")
def downgrade(
    target: str = typer.Argument("-1", help="Revision id или шаг (-1, -2, base)"),
):
    """Откатить миграцию к указанной ревизии (по умолчанию на одну назад)."""
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", target], check=True)
    typer.echo(f"Downgraded to {target}.")


@app.command("migration-history")
def migration_history(
    verbose: bool = typer.Option(False, "-v", help="Развёрнутая история"),
):
    """Показать историю миграций (alembic history)."""
    cmd = [sys.executable, "-m", "alembic", "history"]
    if verbose:
        cmd.append("-v")
    subprocess.run(cmd, check=True)


@app.command("migration-current")
def migration_current():
    """Показать текущую ревизию БД (alembic current)."""
    subprocess.run([sys.executable, "-m", "alembic", "current"], check=True)


# ────────────── Introspection ──────────────


@app.command()
def routes():
    """Список зарегистрированных DSL routes."""
    _bootstrap()
    from src.dsl.commands.registry import route_registry

    route_ids = route_registry.list_routes()
    for route_id in route_ids:
        pipeline = route_registry.get(route_id)
        if pipeline is None:
            continue
        flag = f" [FF:{pipeline.feature_flag}]" if pipeline.feature_flag else ""
        procs = len(pipeline.processors)
        typer.echo(f"  {pipeline.route_id:<40} ({procs} processors){flag}")

    typer.echo(f"\nTotal: {len(route_ids)} routes")


@app.command()
def actions():
    """Список зарегистрированных actions."""
    _bootstrap()
    from src.dsl.commands.registry import action_handler_registry

    action_list = sorted(action_handler_registry.list_actions())
    for action in action_list:
        typer.echo(f"  {action}")

    typer.echo(f"\nTotal: {len(action_list)} actions")


@app.command()
def services():
    """Список зарегистрированных сервисов."""
    _bootstrap()
    from src.core.svcs_registry import list_services

    names = sorted(list_services())
    for name in names:
        typer.echo(f"  {name}")

    typer.echo(f"\nTotal: {len(names)} services")


@app.command()
def health():
    """Проверка здоровья всех компонентов."""
    import asyncio

    _bootstrap()

    async def _check():
        checks = {}
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            checks["redis"] = await redis_client.check_connection()
        except Exception:
            checks["redis"] = False

        try:
            from src.infrastructure.database.database import db_initializer

            checks["database"] = await db_initializer.check_connection()
        except Exception:
            checks["database"] = False

        return checks

    results = asyncio.run(_check())
    for name, ok in results.items():
        status = (
            typer.style("OK", fg=typer.colors.GREEN)
            if ok
            else typer.style("FAIL", fg=typer.colors.RED)
        )
        typer.echo(f"  {name:<20} {status}")


@app.command()
def breakers():
    """Состояние circuit breakers."""
    from src.infrastructure.clients.external.circuit_breakers import breaker_registry

    for info in breaker_registry.get_all_status():
        state = info["state"]
        color = typer.colors.GREEN if state == "closed" else typer.colors.RED
        typer.echo(
            f"  {info['name']:<20} {typer.style(state, fg=color)} (failures: {info['failure_count']})"
        )


# ────────────── Scaffolding ──────────────


scaffold_app = typer.Typer(help="Генерация кода")
app.add_typer(scaffold_app, name="scaffold")


@scaffold_app.command("service")
def scaffold_service(name: str):
    """Генерация Service + Schema + Actions."""
    base = Path("src")
    service_file = base / "services" / f"{name}.py"
    if service_file.exists():
        typer.echo(f"Service {name} already exists!", err=True)
        raise typer.Exit(1)

    class_name = name.capitalize() + "Service"
    content = f'''"""Сервис {name} — автогенерация через manage.py scaffold."""

from src.infrastructure.decorators.singleton import singleton

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
def scaffold_processor(name: str):
    """Генерация DSL processor."""
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Processor"
    file_path = Path("src/dsl/engine/processors") / f"{name}.py"
    if file_path.exists():
        typer.echo(f"Processor {name} already exists!", err=True)
        raise typer.Exit(1)

    content = f'''"""Custom processor: {name}."""

from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor

__all__ = ("{class_name}",)


class {class_name}(BaseProcessor):
    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        # TODO: implement processor logic
        exchange.in_message.set_body(body)
'''
    file_path.write_text(content)
    typer.echo(f"Created: {file_path}")
    typer.echo("Next: add to processors/__init__.py and builder.py")


@scaffold_app.command("route")
def scaffold_route(name: str, source: str = "internal"):
    """Генерация DSL route YAML."""
    file_path = Path("dsl_routes") / f"{name}.dsl.yaml"
    file_path.parent.mkdir(exist_ok=True)

    content = f"""route_id: {name}
source: "{source}:{name}"
description: "Auto-generated route for {name}"
processors:
  - type: log
    level: info
  - type: dispatch_action
    action: "{name}.get"
"""
    file_path.write_text(content)
    typer.echo(f"Created: {file_path}")


# ────────────── Schema Import ──────────────


import_schema_app = typer.Typer(help="Импорт OpenAPI/Postman → Pydantic + DSL-routes")
app.add_typer(import_schema_app, name="import-schema")


def _import_schema_via_gateway(
    source_path: str, *, kind: str, prefix: str, dry_run: bool
) -> None:
    """W24 ImportGateway CLI helper (общий для openapi/postman/wsdl)."""
    import asyncio
    from pathlib import Path

    from src.core.interfaces.import_gateway import ImportSource, ImportSourceKind
    from src.services.integrations import get_import_service

    content = Path(source_path).read_bytes()
    src_obj = ImportSource(kind=ImportSourceKind(kind), content=content, prefix=prefix)
    result = asyncio.run(
        get_import_service().import_and_register(src_obj, register_actions=not dry_run)
    )
    typer.echo(f"connector: {result['connector']} (status={result['status']})")
    typer.echo(f"endpoints: {result['endpoints']}, version: {result['version']}")
    refs = result.get("secret_refs_required") or []
    if refs:
        typer.echo("secret_refs_required:")
        for r in refs:
            typer.echo(f"  - {r['key']}: {r['ref']}  ({r['hint']})")


@import_schema_app.command("openapi")
def import_schema_openapi(
    source: str = typer.Argument(..., help="Путь к OpenAPI 3.x YAML/JSON"),
    prefix: str = typer.Option("ext", "--prefix", help="Префикс operation_id"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Не регистрировать actions"),
):
    """W24 ImportGateway: OpenAPI 3.x → ConnectorSpec в connector_configs."""
    _import_schema_via_gateway(source, kind="openapi", prefix=prefix, dry_run=dry_run)


@import_schema_app.command("postman")
def import_schema_postman(
    source: str = typer.Argument(..., help="Путь к Postman Collection v2.1 JSON"),
    prefix: str = typer.Option("postman", "--prefix", help="Префикс operation_id"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Не регистрировать actions"),
):
    """W24 ImportGateway: Postman v2.1 → ConnectorSpec в connector_configs."""
    _import_schema_via_gateway(source, kind="postman", prefix=prefix, dry_run=dry_run)


@import_schema_app.command("wsdl")
def import_schema_wsdl(
    source: str = typer.Argument(..., help="Путь к WSDL XML или URL"),
    prefix: str = typer.Option("soap", "--prefix", help="Префикс operation_id"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Не регистрировать actions"),
):
    """W24 ImportGateway: WSDL → ConnectorSpec в connector_configs."""
    _import_schema_via_gateway(source, kind="wsdl", prefix=prefix, dry_run=dry_run)


# ────────────── AI Tools ──────────────


@app.command("list-tools")
def list_tools() -> None:
    """Список зарегистрированных AI-инструментов."""
    _bootstrap()
    from src.services.ai.tools import get_tool_registry

    registry = get_tool_registry()
    tools = registry.list()
    for tool in tools:
        required = tool.parameters.get("required") or []
        params = ", ".join(
            f"{p}" + ("*" if p in required else "")
            for p in tool.parameters.get("properties", {})
        )
        typer.echo(f"  {tool.id:<40} {tool.description[:60]}")
        if params:
            typer.echo(f"      args: {params}")

    typer.echo(f"\nTotal: {len(tools)} tools")


@app.command("expose-tool")
def expose_tool(
    service_class: str = typer.Argument(
        ..., help="Dotted path класса сервиса (src.services.X.Y:ServiceCls)."
    ),
    method: str = typer.Argument(..., help="Имя метода сервиса."),
) -> None:
    """Регистрирует метод сервиса как AI-инструмент.

    Пример::

        python manage.py expose-tool src.services.ops.analytics:AnalyticsService summarise
    """
    _bootstrap()
    import importlib

    from src.services.ai.tools import get_tool_registry

    if ":" not in service_class:
        typer.echo("Формат: <module>:<ClassName>", err=True)
        raise typer.Exit(1)

    module_path, class_name = service_class.split(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        typer.echo(f"Класс {class_name} не найден в {module_path}", err=True)
        raise typer.Exit(1)

    registry = get_tool_registry()
    tools = registry.from_service(cls, methods=[method])
    if not tools:
        typer.echo(f"Метод {method} не найден в {class_name}", err=True)
        raise typer.Exit(1)

    for tool in tools:
        typer.echo(f"Exposed: {tool.id} — {tool.description[:80]}")


# ────────────── DSL CLI (W25.1+) ──────────────


dsl_app = typer.Typer(help="DSL operations: hot-reload, write-back, migrations.")
app.add_typer(dsl_app, name="dsl")


@dsl_app.command("reload")
def dsl_reload(
    route_id: str | None = typer.Option(
        None, "--route-id", help="Перезагрузить один route_id; если не указано — все."
    ),
    all_routes: bool = typer.Option(
        False, "--all", help="Полностью пересканировать каталог dsl_routes."
    ),
):
    """W25.1 — ручной триггер reload без watchdog.

    Используется когда watcher отключён (production read-only FS) либо
    для форсированного обновления после ручной правки YAML.
    """
    _bootstrap()
    import asyncio

    from src.core.config.settings import settings as app_settings
    from src.dsl.commands.registry import route_registry
    from src.dsl.yaml_watcher import DSLYamlWatcher

    if route_id is None and not all_routes:
        typer.echo("Укажи --route-id <id> или --all", err=True)
        raise typer.Exit(2)

    watcher = DSLYamlWatcher(
        routes_dir=app_settings.dsl.routes_dir, route_registry=route_registry
    )
    if route_id is not None:
        path = app_settings.dsl.routes_dir / f"{route_id}.yaml"
        if not path.exists():
            typer.echo(f"YAML не найден: {path}", err=True)
            raise typer.Exit(1)
        from src.dsl.yaml_loader import load_pipeline_from_file

        try:
            pipeline = load_pipeline_from_file(path)
            route_registry.register(pipeline)
            typer.echo(
                typer.style(f"Reloaded: {pipeline.route_id}", fg=typer.colors.GREEN)
            )
        except Exception as exc:
            typer.echo(
                typer.style(f"Reload failed: {exc}", fg=typer.colors.RED), err=True
            )
            raise typer.Exit(1) from exc
        return

    report = asyncio.run(watcher.reload_all())
    if report["errors"]:
        typer.echo(
            typer.style(f"Errors: {report['errors']}", fg=typer.colors.RED), err=True
        )
        raise typer.Exit(1)
    typer.echo(
        typer.style(
            f"Reloaded {report['loaded']} routes from {app_settings.dsl.routes_dir}",
            fg=typer.colors.GREEN,
        )
    )


@dsl_app.command("write-yaml")
def dsl_write_yaml(
    route_id: str = typer.Argument(..., help="route_id для сохранения"),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Путь для записи (по умолчанию — store_dir/<route_id>.yaml)",
    ),
    show_diff: bool = typer.Option(
        False, "--diff", help="Показать unified-diff с текущим файлом до записи"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Не писать файл, только показать diff"
    ),
):
    """W25.2 — write-back: Pipeline из RouteRegistry → YAML на диск.

    Доступно только в development environment (env-guard в
    DSLBuilderService). На staging/prod выходит с ошибкой.
    """
    _bootstrap()
    from src.services.dsl.builder_service import DSLBuilderService

    svc = DSLBuilderService(store_dir=output.parent if output else None)
    if not svc.is_write_enabled() and not dry_run:
        typer.echo(
            typer.style(
                "Write-back доступен только в development. Используй --dry-run.",
                fg=typer.colors.RED,
            ),
            err=True,
        )
        raise typer.Exit(2)

    try:
        result = svc.save_route(route_id, dry_run=dry_run)
    except KeyError as exc:
        typer.echo(
            typer.style(f"Route не найден: {exc}", fg=typer.colors.RED), err=True
        )
        raise typer.Exit(1) from exc

    if show_diff or dry_run:
        if result.diff:
            typer.echo("--- DIFF ---")
            typer.echo(result.diff)
        else:
            typer.echo("(no diff)")
    if result.written:
        typer.echo(typer.style(f"Saved: {result.path}", fg=typer.colors.GREEN))
    else:
        typer.echo(typer.style(f"Skipped: {result.reason}", fg=typer.colors.YELLOW))


# ────────────── Validation ──────────────


@app.command()
def validate(route_id: str):
    """Валидация DSL pipeline."""
    _bootstrap()
    from src.dsl.commands.registry import route_registry
    from src.dsl.engine.validation import pipeline_validator

    pipeline = route_registry.get(route_id)
    result = pipeline_validator.validate(pipeline)

    if result.valid:
        typer.echo(
            typer.style(f"Pipeline '{route_id}' is valid.", fg=typer.colors.GREEN)
        )
    else:
        typer.echo(
            typer.style(f"Pipeline '{route_id}' has issues:", fg=typer.colors.RED)
        )

    for issue in result.issues:
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        proc_info = (
            f" (processor #{issue.processor_index})"
            if issue.processor_index is not None
            else ""
        )
        typer.echo(
            f"  [{issue.level.upper()}]{proc_info} {typer.style(issue.message, fg=color)}"
        )


# ────────────── Utils ──────────────


def _bootstrap():
    """Минимальная инициализация для introspection команд."""
    from src.dsl.commands.setup import register_action_handlers
    from src.dsl.routes import register_dsl_routes
    from src.infrastructure.application.service_setup import register_all_services

    register_all_services()
    register_action_handlers()
    register_dsl_routes()


if __name__ == "__main__":
    app()
