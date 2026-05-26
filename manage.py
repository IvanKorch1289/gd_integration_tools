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

    Делегирует выбор бэкенда (uvicorn/granian) в ``src.backend.main:run`` —
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

    cmd = [sys.executable, "-m", "src.backend.main"]
    typer.echo(
        f"Starting backend (server={os.environ.get('APP_SERVER', 'uvicorn')})..."
    )
    os.execvp(cmd[0], cmd)  # noqa: S606  # CLI developer tool: cmd сформирован из sys.executable + фиксированных аргументов


@app.command("http3-serve")
def http3_serve(
    port: int | None = typer.Option(None, help="UDP port (override APP_HTTP3_PORT)"),
    certfile: str | None = typer.Option(
        None, help="PEM cert (override APP_HTTP3_CERTFILE)"
    ),
    keyfile: str | None = typer.Option(
        None, help="PEM key (override APP_HTTP3_KEYFILE)"
    ),
):
    """Запуск опционального HTTP/3 + WebTransport сервера (Sprint 8 opt-in).

    Требует extra ``http3`` (``uv sync --extra http3``) и валидные
    TLS-сертификаты с ALPN h3/h3-29.
    """
    if port is not None:
        os.environ["APP_HTTP3_PORT"] = str(port)
    if certfile is not None:
        os.environ["APP_HTTP3_CERTFILE"] = certfile
    if keyfile is not None:
        os.environ["APP_HTTP3_KEYFILE"] = keyfile
    os.environ["APP_HTTP3_ENABLED"] = "true"

    from src.backend.entrypoints.http3.cli import run_from_settings

    typer.echo("Starting HTTP/3 server (aioquic) ...")
    run_from_settings()


@app.command("run-frontend")
def run_frontend(port: int = typer.Option(8501, help="Streamlit port")):
    """Запуск Streamlit dashboard."""
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "src/frontend/streamlit_app/app.py",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]
    typer.echo(f"Starting Streamlit on :{port}...")
    os.execvp(cmd[0], cmd)  # noqa: S606  # CLI developer tool: cmd сформирован из sys.executable + фиксированных аргументов


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

        backend = subprocess.Popen(  # noqa: S603  # CLI developer tool: фиксированный sys.executable + literal args
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.backend.main:app",
                "--host",
                "0.0.0.0",  # noqa: S104  # CLI developer tool: dev-режим, listen на всех интерфейсах
                "--port",
                str(backend_port),
            ]
        )
        procs.append(backend)

        frontend = subprocess.Popen(  # noqa: S603  # CLI developer tool: фиксированный sys.executable + literal args
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "src/frontend/streamlit_app/app.py",
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
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)  # noqa: S603  # CLI developer tool: фиксированные args
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
    subprocess.run(cmd, check=True)  # noqa: S603  # CLI developer tool: cmd собран из sys.executable + literal alembic args + user-supplied message
    typer.echo(
        "Migration created. Проверь сгенерированный файл в "
        "src/backend/infrastructure/database/migrations/versions/ перед `migrate`."
    )


@app.command("downgrade")
def downgrade(
    target: str = typer.Argument("-1", help="Revision id или шаг (-1, -2, base)"),
):
    """Откатить миграцию к указанной ревизии (по умолчанию на одну назад)."""
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", target], check=True)  # noqa: S603  # CLI developer tool: фиксированные args + revision id
    typer.echo(f"Downgraded to {target}.")


@app.command("migration-history")
def migration_history(
    verbose: bool = typer.Option(False, "-v", help="Развёрнутая история"),
):
    """Показать историю миграций (alembic history)."""
    cmd = [sys.executable, "-m", "alembic", "history"]
    if verbose:
        cmd.append("-v")
    subprocess.run(cmd, check=True)  # noqa: S603  # CLI developer tool: cmd собран из sys.executable + literal alembic args


@app.command("migration-current")
def migration_current():
    """Показать текущую ревизию БД (alembic current)."""
    subprocess.run([sys.executable, "-m", "alembic", "current"], check=True)


# ────────────── Introspection ──────────────


@app.command("validate-profile")
def validate_profile(
    env: str = typer.Argument(
        ..., help="Имя профиля: dev | dev_light | staging | prod"
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="exit 1 при любых WARNING (по умолчанию — только CRITICAL/ERROR).",
    ),
) -> None:
    """Валидация config_profiles/<env>.yml (S18 W9, S-L9-3).

    Проверяет:
        * YAML syntax + наличие файла;
        * базовая schema (app/secure/database/redis sections);
        * ConfigValidator-инварианты для production-профиля
          (waf strict, debug=false, jwt_secret length, и т.д.).

    Exit codes:
        * 0 — без нарушений.
        * 1 — найдены CRITICAL/ERROR нарушения (или WARNING + --strict).
    """
    import yaml  # noqa: PLC0415

    profile_path = Path("config_profiles") / f"{env}.yml"
    if not profile_path.is_file():
        typer.echo(f"[ERROR] Profile not found: {profile_path}", err=True)
        raise typer.Exit(code=1)

    try:
        with profile_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        typer.echo(f"[ERROR] Invalid YAML in {profile_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not isinstance(data, dict):
        typer.echo(
            f"[ERROR] Profile must be a YAML mapping, got {type(data).__name__}",
            err=True,
        )
        raise typer.Exit(code=1)

    # Все профили — overlay поверх base.yml (deep_merge при загрузке).
    # Базовая проверка: наличие хотя бы одной section. Полный invariant
    # check выполняется через runtime ConfigValidator после merge.
    if not data:
        typer.echo(
            f"[ERROR] Profile {env} is empty (no overlay sections)", err=True
        )
        raise typer.Exit(code=1)

    # ConfigValidator-инварианты применимы только для прод (validate-profile
    # дополняет startup-gate, не заменяет полностью runtime валидацию).
    typer.echo(f"[OK] config_profiles/{env}.yml — syntax + schema valid")
    if env == "prod":
        # Минимальная prod-проверка (без полного Settings-load, который
        # требует Vault + env vars): проверка ключевых flags в overlay.
        app_cfg = data.get("app") or {}
        secure_cfg = data.get("secure") or {}
        prod_issues: list[str] = []
        if app_cfg.get("debug") is True or app_cfg.get("debug_mode") is True:
            prod_issues.append("app.debug=true в prod-профиле (B-1 CRITICAL)")
        if app_cfg.get("enable_swagger") is True:
            prod_issues.append("app.enable_swagger=true в prod (S-DOCS-1)")
        if app_cfg.get("enable_redoc") is True:
            prod_issues.append("app.enable_redoc=true в prod (S-DOCS-1)")
        cors_origins = secure_cfg.get("cors_origins")
        if cors_origins == "*" or cors_origins == ["*"]:
            prod_issues.append("secure.cors_origins='*' в prod (B-2 CRITICAL)")
        if prod_issues:
            for issue in prod_issues:
                typer.echo(f"[CRITICAL] {issue}", err=True)
            raise typer.Exit(code=1)
        typer.echo("[OK] prod profile invariants verified")
    if strict and env in {"dev", "dev_light"}:
        typer.echo("[OK] strict-mode не применяет prod-инварианты для dev")


@app.command()
def routes():
    """Список зарегистрированных DSL routes."""
    _bootstrap()
    from src.backend.dsl.commands.registry import route_registry

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
def actions(
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Wave B: завершиться с exit 1, если хоть один ActionSpec получил "
            "action_id неявно (через tier-1 inference или fallback на name)."
        ),
    ),
):
    """Список зарегистрированных actions.

    В strict-режиме дополнительно аудитирует ``ActionSpec``-инстансы и
    завершает процесс с кодом 1 при наличии неявного ``action_id``
    (Wave B — переход к обязательной декларации).
    """
    _bootstrap()
    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.entrypoints.api.generator.specs import audit_action_specs

    action_list = sorted(action_handler_registry.list_actions())
    for action in action_list:
        typer.echo(f"  {action}")

    typer.echo(f"\nTotal: {len(action_list)} actions")

    explicit, inferred = audit_action_specs()
    typer.echo(
        f"\nActionSpec audit: explicit={len(explicit)} inferred={len(inferred)}"
    )

    if inferred:
        typer.echo("\nInferred action_id (Wave B fallback):")
        for spec in sorted(inferred, key=lambda s: (s.path, s.method)):
            typer.echo(
                f"  - {spec.method:<7} {spec.path:<60} "
                f"action_id={spec.action_id!r} (tier={spec.tier}, name={spec.name!r})"
            )

    if strict and inferred:
        typer.echo(
            "\n[strict] FAIL: указанные ActionSpec не содержат явного action_id.",
            err=True,
        )
        raise typer.Exit(code=1)


@app.command()
def services():
    """Список зарегистрированных сервисов."""
    _bootstrap()
    from src.backend.core.svcs_registry import list_services

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
            from src.backend.infrastructure.clients.storage.redis import redis_client

            checks["redis"] = await redis_client.check_connection()
        except Exception:
            checks["redis"] = False

        try:
            from src.backend.infrastructure.database.database import db_initializer

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
    from src.backend.infrastructure.clients.external.circuit_breakers import (
        breaker_registry,
    )

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
def scaffold_processor(name: str):
    """Генерация DSL processor."""
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Processor"
    file_path = Path("src/backend/dsl/engine/processors") / f"{name}.py"
    if file_path.exists():
        typer.echo(f"Processor {name} already exists!", err=True)
        raise typer.Exit(1)

    content = f'''"""Custom processor: {name}."""

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

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


@scaffold_app.command("codegen-service")
def scaffold_codegen_service(
    name: str = typer.Option(..., help="snake_case имя сервиса (мн.ч.)"),
    domain: str = typer.Option(..., help="core | ai | integrations | ..."),
    crud: bool = typer.Option(False, "--crud/--no-crud", help="включить CRUD-методы"),
    fields: str = typer.Option(
        "{}", help='JSON {"field":"py_type"} для Create/Update схем'
    ),
    model_class: str | None = typer.Option(
        None, "--model-class", help="имя SQLAlchemy-модели (default: PascalCase singular)"
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
    output: str = typer.Option(
        "-", help="путь YAML; '-' (default) — stdout"
    ),
) -> None:
    """Wave 5.5 — фасад над `tools/codegen_extract.py` через Typer."""
    from tools.codegen_extract import main as _extract_main

    raise typer.Exit(_extract_main(["--service", service, "--output", output]))


# ────────────── Schema Import ──────────────


import_schema_app = typer.Typer(help="Импорт OpenAPI/Postman → Pydantic + DSL-routes")
app.add_typer(import_schema_app, name="import-schema")


def _import_schema_via_gateway(
    source_path: str, *, kind: str, prefix: str, dry_run: bool
) -> None:
    """W24 ImportGateway CLI helper (общий для openapi/postman/wsdl)."""
    import asyncio
    from pathlib import Path

    from src.backend.core.interfaces.import_gateway import (
        ImportSource,
        ImportSourceKind,
    )
    from src.backend.services.integrations import get_import_service

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
    from src.backend.services.ai.tools import get_tool_registry

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
        ..., help="Dotted path класса сервиса (src.backend.services.X.Y:ServiceCls)."
    ),
    method: str = typer.Argument(..., help="Имя метода сервиса."),
) -> None:
    """Регистрирует метод сервиса как AI-инструмент.

    Пример::

        python manage.py expose-tool src.backend.services.ops.analytics:AnalyticsService summarise
    """
    _bootstrap()
    import importlib

    from src.backend.services.ai.tools import get_tool_registry

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

    from src.backend.core.config.settings import settings as app_settings
    from src.backend.dsl.commands.registry import route_registry
    from src.backend.dsl.yaml_watcher import DSLYamlWatcher

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
        from src.backend.dsl.yaml_loader import load_pipeline_from_file

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


@dsl_app.command("lint")
def dsl_lint(
    path: Path = typer.Argument(
        ..., help="Каталог с route.toml или *.dsl.yaml файл"
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Strict-mode (warnings → errors, для CI)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Вывод в JSON"),
):
    """K3 S6 [wave:s6/k3-dsl-linter-lsp] — расширенный DSL Linter.

    Проверяет route.toml + *.dsl.yaml на:
    schema / capability declarations / reference checks / plugin-aware
    discovery (extensions/<name>/plugin.toml).

    Exit-code 1 при errors, 0 при успехе. В strict-mode warnings = errors.
    """
    from src.backend.dsl.cli.linter import main as linter_main

    argv: list[str] = [str(path)]
    if strict:
        argv.append("--strict")
    if json_output:
        argv.append("--json")
    raise typer.Exit(linter_main(argv))


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
    from src.backend.services.dsl.builder_service import DSLBuilderService

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


@dsl_app.command("migrate")
def dsl_migrate(
    target: str = typer.Option(
        "v2", "--target", help="Целевая apiVersion (default: текущая)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Показать diff'ы вместо записи"
    ),
    routes_dir: Path | None = typer.Option(
        None, "--routes-dir", help="Override каталог DSL-маршрутов"
    ),
):
    """W25.3 — массовая миграция dsl_routes/*.yaml до целевой apiVersion.

    Без ``--dry-run`` файлы перезаписываются. С ``--dry-run`` показывает
    unified-diff'ы. Уже актуальные spec'ы пропускаются.
    """
    import difflib

    import yaml

    from src.backend.core.config.settings import settings as app_settings
    from src.backend.dsl.versioning import apply_migrations

    target_dir = routes_dir or app_settings.dsl.routes_dir
    if not target_dir.exists():
        typer.echo(f"Каталог не существует: {target_dir}", err=True)
        raise typer.Exit(1)

    files = sorted(target_dir.glob("**/*.yaml")) + sorted(
        target_dir.glob("**/*.dsl.yaml")
    )
    if not files:
        typer.echo(f"Нет YAML-файлов в {target_dir}")
        return

    migrated = 0
    skipped = 0
    for path in files:
        original = path.read_text(encoding="utf-8")
        spec = yaml.safe_load(original) or {}
        if not isinstance(spec, dict):
            typer.echo(f"  skip {path}: root не dict")
            skipped += 1
            continue

        if spec.get("apiVersion") == target:
            skipped += 1
            continue

        new_spec = apply_migrations(spec, target_version=target)
        new_yaml = yaml.safe_dump(new_spec, sort_keys=False, allow_unicode=True)

        if dry_run:
            diff = "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    new_yaml.splitlines(keepends=True),
                    fromfile=str(path),
                    tofile=f"{path} (migrated)",
                )
            )
            if diff:
                typer.echo(diff)
            migrated += 1
        else:
            path.write_text(new_yaml, encoding="utf-8")
            typer.echo(typer.style(f"  migrated: {path}", fg=typer.colors.GREEN))
            migrated += 1

    summary = f"Migrate {target}: {migrated} migrated, {skipped} already at target"
    typer.echo(typer.style(summary, fg=typer.colors.CYAN))


# ────────────── Validation ──────────────


@app.command()
def validate(route_id: str):
    """Валидация DSL pipeline."""
    _bootstrap()
    from src.backend.dsl.commands.registry import route_registry
    from src.backend.dsl.engine.validation import pipeline_validator

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
    from src.backend.dsl.commands.setup import register_action_handlers
    from src.backend.dsl.routes import register_dsl_routes
    from src.backend.plugins.composition.service_setup import register_all_services

    register_all_services()
    register_action_handlers()
    register_dsl_routes()

    # Wave 1.1 (Roadmap V10): импорт v1 routers триггерит регистрацию
    # Tier 1 CRUD-actions через ``ActionRouterBuilder`` (в дополнение к
    # ручным action handlers выше). Без этого ``manage.py actions`` не
    # отображал бы CRUD-action_id (``orders.list``/``orders.create`` и т.п.).
    try:
        from src.backend.entrypoints.api.v1.routers import get_v1_routers

        get_v1_routers()
    except Exception as exc:  # noqa: BLE001, S110
        # Introspection не должна падать из-за опциональных зависимостей
        # (например, vault/graypy/мини-профилей). Логируем на DEBUG.
        import logging

        logging.getLogger("manage").debug(
            "get_v1_routers пропущен в bootstrap: %s", exc
        )


workflow_app = typer.Typer(help="Workflow DSL management (Sprint 4).")
app.add_typer(workflow_app, name="workflow")


@workflow_app.command("import")
def workflow_import(
    file: Path = typer.Option(..., "--file", help="Путь до BPMN/YAML файла."),
    fmt: str = typer.Option(
        "bpmn", "--format", help="Формат входного файла: bpmn | yaml."
    ),
    name: str | None = typer.Option(None, "--name", help="Имя workflow (override)."),
    show: bool = typer.Option(
        False, "--show", help="Вывести JSON-представление workflow в stdout."
    ),
) -> None:
    """Импорт workflow из BPMN 2.0 или YAML в WorkflowCompilerRegistry (Sprint 4 Wave B).

    Поддерживает форматы:
        * ``bpmn`` — BPMN 2.0 XML через :mod:`dsl.workflow.bpmn_importer`.
        * ``yaml`` — YAML-декларация через :mod:`dsl.workflow.yaml_io`.

    Args:
        file: Путь к файлу.
        fmt: Формат (bpmn | yaml).
        name: Опц. имя workflow (override default).
        show: Если True — печатает model_dump в stdout.
    """
    if not file.exists():
        typer.echo(f"ERR: файл не найден: {file}", err=True)
        raise typer.Exit(code=2)

    content = file.read_text(encoding="utf-8")

    if fmt == "bpmn":
        from src.backend.dsl.workflow.bpmn_importer import import_bpmn

        declaration = import_bpmn(content, name=name, check_feature_flag=False)
    elif fmt == "yaml":
        from src.backend.dsl.workflow.yaml_io import from_yaml

        declaration = from_yaml(content)
        if name is not None:
            declaration = declaration.model_copy(update={"name": name})
    else:
        typer.echo(f"ERR: неизвестный формат: {fmt!r} (ожидалось bpmn|yaml)", err=True)
        raise typer.Exit(code=2)

    typer.echo(
        f"Workflow импортирован: name={declaration.name!r}, "
        f"steps={len(declaration.steps)}, version={declaration.version}"
    )
    if show:
        import json

        typer.echo(json.dumps(declaration.model_dump(mode="json"), indent=2, ensure_ascii=False))


@workflow_app.command("dryrun")
def workflow_dryrun(
    file: Path = typer.Option(..., "--file", help="Путь до BPMN/YAML файла workflow."),
    fmt: str = typer.Option(
        "yaml", "--format", help="Формат входного файла: bpmn | yaml."
    ),
    input: str | None = typer.Option(  # noqa: A002
        None, "--input", help="JSON входные данные для workflow."
    ),
    record: bool = typer.Option(
        False, "--record", help="Записать trace в .dryrun_trace.json."
    ),
    replay: Path | None = typer.Option(
        None, "--replay", help="Путь до .dryrun_trace.json для replay-режима."
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Сохранить JSON-отчёт в файл (default — stdout)."
    ),
) -> None:
    """K3 S5 W10 — workflow dryrun: симуляция выполнения без подключения к Temporal.

    Возвращает JSON-отчёт со списком activities + signals + timer-fires + state
    transitions. Поддерживает три режима:

    * нормальный: симуляция с input через детерминированный fake-runtime;
    * ``--record``: записывает trace в ``.dryrun_trace.json`` для regression-тестов;
    * ``--replay <file>``: повторяет ранее записанный trace (fail-on-mismatch).

    Под feature flag ``feature_flags.workflow_dryrun_enabled`` (default-OFF).

    Args:
        file: Путь до workflow YAML/BPMN.
        fmt: Формат (bpmn|yaml).
        input: JSON-payload входа.
        record: Записать trace.
        replay: Replay из существующего trace.
        out: Куда сохранить отчёт.
    """
    import json

    try:
        from src.backend.core.config.features import feature_flags

        if not feature_flags.workflow_dryrun_enabled:
            typer.echo(
                "WARN: feature_flags.workflow_dryrun_enabled = False; "
                "выполняется в read-only режиме (без записи trace).",
                err=True,
            )
    except Exception:  # noqa: BLE001
        pass

    if not file.exists():
        typer.echo(f"ERR: файл не найден: {file}", err=True)
        raise typer.Exit(code=2)

    content = file.read_text(encoding="utf-8")

    if fmt == "bpmn":
        from src.backend.dsl.workflow.bpmn_importer import import_bpmn

        declaration = import_bpmn(content, check_feature_flag=False)
    elif fmt == "yaml":
        from src.backend.dsl.workflow.yaml_io import from_yaml

        declaration = from_yaml(content)
    else:
        typer.echo(f"ERR: неизвестный формат: {fmt!r}", err=True)
        raise typer.Exit(code=2)

    input_data: dict = {}
    if input:
        try:
            input_data = json.loads(input)
        except json.JSONDecodeError as exc:
            typer.echo(f"ERR: --input не валидный JSON: {exc}", err=True)
            raise typer.Exit(code=2)

    # Запуск симуляции (lazy-import чтобы не подтягивать temporal SDK).
    from src.backend.dsl.workflow.dryrun import run_workflow_dryrun

    report = run_workflow_dryrun(
        declaration=declaration,
        input_data=input_data,
    )

    if record:
        trace_path = Path(".dryrun_trace.json")
        trace_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        typer.echo(f"Trace записан в {trace_path}")

    if replay is not None:
        if not replay.exists():
            typer.echo(f"ERR: replay-файл не найден: {replay}", err=True)
            raise typer.Exit(code=2)
        expected = json.loads(replay.read_text(encoding="utf-8"))
        if expected.get("activities") != report.get("activities"):
            typer.echo(
                f"FAIL: replay mismatch! activities differ:\n"
                f"  expected: {expected.get('activities')}\n"
                f"  got:      {report.get('activities')}",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo("OK: replay matches recorded trace")

    output = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    if out is not None:
        out.write_text(output, encoding="utf-8")
        typer.echo(f"Отчёт сохранён в {out}")
    else:
        typer.echo(output)


@workflow_app.command("version")
def workflow_version(
    name: str = typer.Argument(..., help="Имя workflow (workflow_id)."),
    show_all: bool = typer.Option(
        False, "--all", help="Показать все workflow_id в реестре."
    ),
) -> None:
    """Sprint 7 K3 — current + history workflow версий из WorkflowVersionRegistry.

    Выводит default-версию (current) и полную history по semver. Реестр
    заполняется через декоратор ``@workflow_versioned("X.Y.Z")`` при
    импорте workflow-модулей. Под feature flag
    ``feature_flags.workflow_versioning_strict`` (default-OFF).

    Args:
        name: workflow_id (или любая строка при ``--all``).
        show_all: Вывести все workflow_id, зарегистрированные в реестре.
    """
    from src.backend.dsl.workflow.versioning import get_global_registry

    registry = get_global_registry()

    if show_all:
        ids = registry.all_workflow_ids()
        if not ids:
            typer.echo("Реестр workflow версий пуст.")
            return
        typer.echo(f"Registered workflows ({len(ids)}):")
        for wf_id in ids:
            current = registry.get_default(wf_id)
            current_str = f"v{current.semver}" if current else "(no default)"
            typer.echo(f"  - {wf_id}: current={current_str}")
        return

    current = registry.get_default(name)
    history = registry.history(name)

    if not history:
        typer.echo(f"Workflow {name!r} не найден в реестре.", err=True)
        raise typer.Exit(code=1)

    if current is not None:
        typer.echo(f"Current default: {name} v{current.semver}")
    else:
        typer.echo(f"Workflow {name}: default-версия не назначена.")

    typer.echo(f"History ({len(history)}):")
    for v in history:
        marker = " (default)" if v.default_version else ""
        typer.echo(f"  - v{v.semver}{marker}")


@workflow_app.command("cancel")
def workflow_cancel(
    workflow_id: str = typer.Argument(..., help="Workflow ID (Temporal)."),
    reason: str = typer.Option("", "--reason", help="Причина отмены."),
    namespace: str = typer.Option(
        "default", "--namespace", help="Workflow namespace."
    ),
) -> None:
    """Sprint 12 K3 W7 — отменить running workflow по ID.

    Использует :class:`WorkflowBackend.cancel_workflow` и эмитит
    audit-event ``workflow.cancel`` через
    :class:`WorkflowAuditSink` (если зарегистрирован).

    Пример::

        python manage.py workflow cancel wf-abc-123 --reason "user_requested"
    """
    import asyncio

    async def _run() -> int:
        from src.backend.core.workflow.backend import WorkflowHandle
        from src.backend.infrastructure.workflow.factory import (
            create_workflow_backend,
        )

        backend = await create_workflow_backend(kind="auto")
        handle = WorkflowHandle(
            workflow_id=workflow_id,
            run_id=workflow_id,
            namespace=namespace,
        )
        try:
            await backend.cancel_workflow(handle=handle)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"ERR: cancel failed: {exc}", err=True)
            return 1

        try:
            from src.backend.services.audit.workflow_audit_sink import (
                get_workflow_audit_sink,
            )

            sink = get_workflow_audit_sink()
            if sink is not None:
                await sink.emit(
                    event_type="workflow.cancel",
                    workflow_id=workflow_id,
                    tenant_id=None,
                    payload={
                        "reason": reason,
                        "caller": "manage.py",
                        "namespace": namespace,
                    },
                )
        except Exception:  # noqa: BLE001
            pass

        typer.echo(f"OK: cancelled workflow {workflow_id!r} (reason={reason!r})")
        return 0

    exit_code = asyncio.run(_run())
    raise typer.Exit(code=exit_code)


# ────────────── Plugin runtime (Sprint 7 T5) ──────────────


plugin_app = typer.Typer(help="Plugin runtime operations (hot-swap, scaffold).")
app.add_typer(plugin_app, name="plugin")


@plugin_app.command("hot-swap")
def plugin_hot_swap(
    name: str = typer.Argument(..., help="Имя плагина (из plugin.toml)"),
):
    """Hot-swap (reload без рестарта) одного in-tree плагина.

    Перечитывает ``extensions/<name>/plugin.toml``, перезагружает Python-
    модуль ``entry_class`` через :func:`importlib.reload`, заново выполняет
    capability allocation и lifecycle. Audit-event ``plugin.hot_swap``
    логируется через CapabilityGate.

    Пример::

        python manage.py plugin hot-swap example_plugin
    """
    import asyncio

    async def _run() -> int:
        try:
            # Lazy-import, чтобы CLI стартовал быстро.
            from src.backend.core.plugin_runtime.hot_swap import (
                HotSwapError,
                hot_swap,
            )
        except ImportError as exc:
            typer.echo(f"ERR: hot_swap unavailable: {exc}", err=True)
            return 1

        # PluginLoaderV11 живёт в app.state — поднимаем минимальное
        # bootstrap-окружение, чтобы CLI мог дотянуться до loader.
        # В Sprint 7 — stub: ищем app.state.plugin_loader_v11, если
        # приложение уже запущено. Иначе создаём свежий loader для
        # in-tree скана.
        loader = None
        try:
            from src.backend.main import app as fastapi_app  # noqa: PLC0415

            loader = getattr(fastapi_app.state, "plugin_loader_v11", None)
        except Exception:  # noqa: BLE001 — best-effort lookup
            loader = None

        if loader is None:
            typer.echo(
                "ERR: PluginLoader не инициализирован (app.state.plugin_loader_v11). "
                "Запустите приложение с FEATURE_PLUGIN_LOADER_ENABLED=true.",
                err=True,
            )
            return 1

        try:
            result = await hot_swap(name, loader)
        except HotSwapError as exc:
            typer.echo(f"Plugin not found / hot-swap failed: {exc}", err=True)
            return 1

        typer.echo(
            f"Plugin {result.plugin_name}: {result.old_version} → "
            f"{result.new_version} ({result.status})"
        )
        if result.reason:
            typer.echo(f"  reason: {result.reason}")
        return 0 if result.status == "reloaded" else 1

    raise typer.Exit(asyncio.run(_run()))


@plugin_app.command("new")
def plugin_new(
    name: str = typer.Argument(..., help="snake_case имя плагина"),
):
    """Создать каркас V11 плагина в ``extensions/<name>/``.

    Эквивалент ``make new-plugin NAME=<name>``.
    """
    try:
        from tools.codegen_plugin import scaffold_plugin
    except ImportError as exc:
        typer.echo(f"ERR: codegen_plugin недоступен: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        plugin_root = scaffold_plugin(name)
    except (FileExistsError, ValueError) as exc:
        typer.echo(f"ERR: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Created plugin: {plugin_root}")
    typer.echo(
        f"Next: edit {plugin_root}/plugin.toml and {plugin_root}/plugin.py"
    )


@plugin_app.command("serve")
def plugin_serve(
    name: str = typer.Option(..., "--name", help="Имя плагина (extensions/<name>)"),
    port: int = typer.Option(8001, "--port", help="Порт backend dev-сервера"),
    watch: bool = typer.Option(False, "--watch", help="Hot-reload через watchfiles"),
) -> None:
    """Sprint 14 K5 W4: запуск local dev-сервера с одним плагином."""
    import sys as _sys  # noqa: PLC0415
    from importlib import util as _util  # noqa: PLC0415

    pds_path = Path(__file__).resolve().parent / "tools" / "plugin_dev_server.py"
    spec = _util.spec_from_file_location("_gdit_plugin_dev_server", pds_path)
    if spec is None or spec.loader is None:
        typer.echo(f"ERR: plugin_dev_server недоступен: {pds_path}", err=True)
        raise typer.Exit(1)
    module = _util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = ["--name", name, "--port", str(port)]
    if watch:
        argv.append("--watch")
    raise typer.Exit(module.main(argv))


@plugin_app.command("publish")
def plugin_publish(
    name: str = typer.Option(..., "--plugin", help="Имя плагина (extensions/<name>)"),
    version: str = typer.Option(..., "--version", help="SemVer плагина"),
    cosign_key: Path | None = typer.Option(
        None, "--cosign-key", help="Путь к приватному ключу cosign"
    ),
    marketplace_url: str | None = typer.Option(
        None, "--marketplace-url", envvar="MARKETPLACE_URL"
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    skip_sbom: bool = typer.Option(False, "--skip-sbom"),
    skip_cosign: bool = typer.Option(False, "--skip-cosign"),
    skip_upload: bool = typer.Option(False, "--skip-upload"),
) -> None:
    """Sprint 14 W3: bundle + SBOM + cosign + upload плагина."""
    from tools.publish_plugin import PublishConfig, run as publish_run  # noqa: PLC0415

    plugin_dir = Path("extensions") / name
    cfg = PublishConfig(
        plugin=name,
        version=version,
        plugin_dir=plugin_dir,
        cosign_key=cosign_key,
        marketplace_url=marketplace_url,
        dry_run=dry_run,
        skip_sbom=skip_sbom,
        skip_cosign=skip_cosign,
        skip_upload=skip_upload,
    )
    result = publish_run(cfg)
    for msg in result.messages:
        typer.echo(f"[publish-plugin] {msg}")
    raise typer.Exit(0)


# ────────────── AI Eval (K4 Sprint 6 Wave 1) ──────────────


ai_eval_app = typer.Typer(help="AI eval framework (Inspect AI nightly suites).")
app.add_typer(ai_eval_app, name="ai-eval")


@ai_eval_app.command("nightly")
def ai_eval_nightly(
    artifacts_dir: Path = typer.Option(
        Path("artifacts/inspect-ai"),
        "--artifacts-dir",
        help="Каталог для JSON+Markdown отчётов nightly run.",
    ),
) -> None:
    """K4 S6 W1: запуск всех reference Inspect AI suite + report.

    Активируется feature_flag ``inspect_ai_eval_enabled`` (default-OFF).
    При отсутствии ``inspect-ai`` SDK (extra ``ai``) скип gracefully.
    """
    from src.backend.services.ai.eval import InspectRunner

    runner = InspectRunner(artifacts_dir=artifacts_dir)
    if not runner.is_enabled():
        typer.echo(
            typer.style(
                "InspectRunner disabled (FEATURE_INSPECT_AI_EVAL_ENABLED=false). "
                "Включите feature-flag для запуска.",
                fg=typer.colors.YELLOW,
            )
        )
        raise typer.Exit(code=0)

    summary = runner.run_all(write_artifacts=True)
    typer.echo(typer.style(f"Suites: {len(summary.suites)}", fg=typer.colors.CYAN))
    typer.echo(typer.style(f"Total samples: {summary.total_samples}", fg=typer.colors.CYAN))
    if summary.failed:
        typer.echo(typer.style(f"Failed: {summary.failed}", fg=typer.colors.RED))
        raise typer.Exit(code=1)
    typer.echo(typer.style("OK", fg=typer.colors.GREEN))


@ai_eval_app.command("suite")
def ai_eval_suite(
    suite_name: str = typer.Argument(..., help="Имя suite (knowledge_qa, safety_classifier, ...)."),
    artifacts_dir: Path = typer.Option(
        Path("artifacts/inspect-ai"),
        "--artifacts-dir",
        help="Каталог для отчётов.",
    ),
) -> None:
    """K4 S6 W1: запуск одного suite по имени.

    Полезно для локальной отладки добавленного suite.
    """
    from src.backend.services.ai.eval import REFERENCE_SUITES, InspectRunner

    suite = next((s for s in REFERENCE_SUITES if s.name == suite_name), None)
    if suite is None:
        typer.echo(
            typer.style(
                f"Suite '{suite_name}' не найден. Доступные: "
                + ", ".join(s.name for s in REFERENCE_SUITES),
                fg=typer.colors.RED,
            ),
            err=True,
        )
        raise typer.Exit(code=2)

    runner = InspectRunner(artifacts_dir=artifacts_dir, suites=[suite])
    summary = runner.run_all(write_artifacts=True)
    typer.echo(summary.to_markdown())


# ────────────── Shell Completions ──────────────


completions_app = typer.Typer(help="Install shell completions for gd-tools CLI")
app.add_typer(completions_app, name="completions")


@completions_app.command("install")
def completions_install(
    shell: str = typer.Option(
        ..., "--shell", "-s",
        help="Shell type: bash | zsh | fish | powershell"
    ),
) -> None:
    """Install shell completions for gd-tools CLI.

    Example:
        python manage.py completions install --shell bash
        python manage.py completions install --shell zsh
    """
    from typer import completion
    from typer import main as typer_main

    valid_shells = {"bash", "zsh", "fish", "powershell", "pwsh"}
    if shell not in valid_shells:
        typer.echo(
            f"Shell '{shell}' not supported. Valid options: {', '.join(sorted(valid_shells))}",
            err=True,
        )
        raise typer.Exit(code=1)

    # Get the underlying Click command and install completions
    click_cmd = typer_main.get_command(app)
    prog_name = click_cmd.info_name or "gd-tools"
    complete_var = f"_{prog_name.replace('-', '_').upper()}_COMPLETE"

    try:
        installed_shell, installed_path = completion.install(
            shell=shell, prog_name=prog_name, complete_var=complete_var
        )
        typer.secho(
            f"{installed_shell} completion installed in {installed_path}",
            fg=typer.colors.GREEN,
        )
        typer.echo("Completion will take effect once you restart the terminal")
    except Exception as exc:
        typer.echo(f"Failed to install completions: {exc}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
