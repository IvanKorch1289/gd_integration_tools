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
    name="gd-tools",
    help="GD Integration Tools — management CLI",
    add_completion=True,
)


# ────────────── Runtime ──────────────


@app.command()
def run(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    workers: int = typer.Option(1, help="Uvicorn workers"),
    reload: bool = typer.Option(False, help="Auto-reload on changes"),
):
    """Запуск FastAPI backend."""
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", host, "--port", str(port), "--workers", str(workers),
    ]
    if reload:
        cmd.append("--reload")
    typer.echo(f"Starting backend on {host}:{port}...")
    os.execvp(cmd[0], cmd)


@app.command("run-frontend")
def run_frontend(
    port: int = typer.Option(8501, help="Streamlit port"),
):
    """Запуск Streamlit dashboard."""
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "src/entrypoints/streamlit_app/app.py",
        "--server.port", str(port),
        "--server.headless", "true",
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
        typer.echo(f"Starting backend on :{backend_port} + frontend on :{frontend_port}...")

        backend = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "0.0.0.0", "--port", str(backend_port),
        ])
        procs.append(backend)

        frontend = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run",
            "src/entrypoints/streamlit_app/app.py",
            "--server.port", str(frontend_port),
            "--server.headless", "true",
        ])
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
def migrate(message: str = typer.Option("", help="Migration message")):
    """Применить миграции (alembic upgrade head)."""
    if message:
        subprocess.run([sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", message], check=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    typer.echo("Migrations applied.")


# ────────────── Introspection ──────────────


@app.command()
def routes():
    """Список зарегистрированных DSL routes."""
    _bootstrap()
    from app.dsl.commands.registry import route_registry

    for route in route_registry.list_routes():
        flag = f" [FF:{route.feature_flag}]" if route.feature_flag else ""
        procs = len(route.processors)
        typer.echo(f"  {route.route_id:<40} ({procs} processors){flag}")

    typer.echo(f"\nTotal: {len(route_registry.list_routes())} routes")


@app.command()
def actions():
    """Список зарегистрированных actions."""
    _bootstrap()
    from app.dsl.commands.registry import action_handler_registry

    action_list = sorted(action_handler_registry.list_actions())
    for action in action_list:
        typer.echo(f"  {action}")

    typer.echo(f"\nTotal: {len(action_list)} actions")


@app.command()
def services():
    """Список зарегистрированных сервисов."""
    _bootstrap()
    from app.core.service_registry import service_registry

    for name in sorted(service_registry.list_services()):
        typer.echo(f"  {name}")

    typer.echo(f"\nTotal: {len(service_registry.list_services())} services")


@app.command()
def health():
    """Проверка здоровья всех компонентов."""
    import asyncio
    _bootstrap()

    async def _check():
        checks = {}
        try:
            from app.infrastructure.clients.storage.redis import redis_client
            checks["redis"] = await redis_client.check_connection()
        except Exception:
            checks["redis"] = False

        try:
            from app.infrastructure.db.database import db_initializer
            checks["database"] = await db_initializer.check_connection()
        except Exception:
            checks["database"] = False

        return checks

    results = asyncio.run(_check())
    for name, ok in results.items():
        status = typer.style("OK", fg=typer.colors.GREEN) if ok else typer.style("FAIL", fg=typer.colors.RED)
        typer.echo(f"  {name:<20} {status}")


@app.command()
def breakers():
    """Состояние circuit breakers."""
    from app.infrastructure.clients.external.circuit_breakers import breaker_registry

    for info in breaker_registry.get_all_status():
        state = info["state"]
        color = typer.colors.GREEN if state == "closed" else typer.colors.RED
        typer.echo(f"  {info['name']:<20} {typer.style(state, fg=color)} (failures: {info['failure_count']})")


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

from app.core.decorators.singleton import singleton

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
    typer.echo(f"Next: register in src/core/service_setup.py and src/dsl/commands/setup.py")


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

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

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
    typer.echo(f"Next: add to processors/__init__.py and builder.py")


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


# ────────────── Validation ──────────────


@app.command()
def validate(route_id: str):
    """Валидация DSL pipeline."""
    _bootstrap()
    from app.dsl.commands.registry import route_registry
    from app.dsl.engine.validation import pipeline_validator

    pipeline = route_registry.get(route_id)
    result = pipeline_validator.validate(pipeline)

    if result.valid:
        typer.echo(typer.style(f"Pipeline '{route_id}' is valid.", fg=typer.colors.GREEN))
    else:
        typer.echo(typer.style(f"Pipeline '{route_id}' has issues:", fg=typer.colors.RED))

    for issue in result.issues:
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        proc_info = f" (processor #{issue.processor_index})" if issue.processor_index is not None else ""
        typer.echo(f"  [{issue.level.upper()}]{proc_info} {typer.style(issue.message, fg=color)}")


# ────────────── Utils ──────────────


def _bootstrap():
    """Минимальная инициализация для introspection команд."""
    from app.core.service_setup import register_all_services
    from app.dsl.commands.setup import register_action_handlers
    from app.dsl.routes import register_dsl_routes

    register_all_services()
    register_action_handlers()
    register_dsl_routes()


if __name__ == "__main__":
    app()
