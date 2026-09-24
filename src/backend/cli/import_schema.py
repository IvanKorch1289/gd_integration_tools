"""Import-schema sub-app для ``manage.py``.

P1 CLI decomposition W8 (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability. ``import-schema`` — Typer sub-app с 3
subcommands для W24 ImportGateway CLI (OpenAPI/Postman/WSDL → ConnectorSpec).

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py import-schema openapi <source> [--prefix ext] [--dry-run]``
  — OpenAPI 3.x → ConnectorSpec.
- ``python manage.py import-schema postman <source> [--prefix postman] [--dry-run]``
  — Postman Collection v2.1 → ConnectorSpec.
- ``python manage.py import-schema wsdl <source> [--prefix soap] [--dry-run]``
  — WSDL → ConnectorSpec.

Typer sub-app pattern (consistent с W5 scaffold + W6 workflow):
- ``import_schema_app = typer.Typer(help="Импорт OpenAPI/Postman → ..." )``
- ``app.add_typer(import_schema_app, name="import-schema")`` в manage.py
- Команды регистрируются через ``@import_schema_app.command("name")``
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

import_schema_app = typer.Typer(help="Импорт OpenAPI/Postman → Pydantic + DSL-routes")


def _import_schema_via_gateway(
    source_path: str, *, kind: str, prefix: str, dry_run: bool
) -> None:
    """W24 ImportGateway CLI helper (общий для openapi/postman/wsdl)."""
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
) -> None:
    """W24 ImportGateway: OpenAPI 3.x → ConnectorSpec в connector_configs."""
    _import_schema_via_gateway(source, kind="openapi", prefix=prefix, dry_run=dry_run)


@import_schema_app.command("postman")
def import_schema_postman(
    source: str = typer.Argument(..., help="Путь к Postman Collection v2.1 JSON"),
    prefix: str = typer.Option("postman", "--prefix", help="Префикс operation_id"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Не регистрировать actions"),
) -> None:
    """W24 ImportGateway: Postman v2.1 → ConnectorSpec в connector_configs."""
    _import_schema_via_gateway(source, kind="postman", prefix=prefix, dry_run=dry_run)


@import_schema_app.command("wsdl")
def import_schema_wsdl(
    source: str = typer.Argument(..., help="Путь к WSDL XML или URL"),
    prefix: str = typer.Option("soap", "--prefix", help="Префикс operation_id"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Не регистрировать actions"),
) -> None:
    """W24 ImportGateway: WSDL → ConnectorSpec в connector_configs."""
    _import_schema_via_gateway(source, kind="wsdl", prefix=prefix, dry_run=dry_run)


__all__ = ("import_schema_app",)
