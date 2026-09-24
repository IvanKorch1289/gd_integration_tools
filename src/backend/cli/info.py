"""Info introspection commands для ``manage.py``.

P1 CLI decomposition (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability — каждая Typer-команда должна иметь один
canonical placement. ``routes``, ``actions``, ``services`` — read-only
introspection, нет side effects.

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py routes`` — список зарегистрированных DSL routes.
- ``python manage.py actions [--strict]`` — список actions + audit.
- ``python manage.py services`` — список сервисов.

NOT @app.command() decorated здесь — manage.py imports + decorates для
сохранения CLI contract (top-level команды). Это позволяет Typer sub-app
``add_typer(info_app, name="info")`` будущей wave без дублирования.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from src.backend.cli._bootstrap import bootstrap

if TYPE_CHECKING:
    pass


def routes() -> None:
    """Список зарегистрированных DSL routes."""
    bootstrap()
    from src.backend.dsl.commands.registry import route_registry

    route_ids = route_registry.list_routes()
    for route_id in route_ids:
        pipeline = route_registry.get(route_id)
        if pipeline is None:
            continue
        flag = f" [FF:{pipeline.feature_flag}]" if pipeline.feature_flag else ""
        procs = len(pipeline.processors)
        route_name = typer.style(pipeline.route_id, fg=typer.colors.CYAN, bold=True)
        procs_str = typer.style(f"({procs} processors)", fg=typer.colors.GREEN)
        flag_str = typer.style(flag, fg=typer.colors.YELLOW) if flag else ""
        typer.echo(f"  {route_name:<40} {procs_str}{flag_str}")

    total_str = typer.style(
        f"Total: {len(route_ids)} routes", fg=typer.colors.BLUE, bold=True
    )
    typer.echo(f"\n{total_str}")


def actions(
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Wave B: завершиться с exit 1, если хоть один ActionSpec получил "
            "action_id неявно (через tier-1 inference или fallback на name)."
        ),
    ),
) -> None:
    """Список зарегистрированных actions.

    В strict-режиме дополнительно аудитирует ``ActionSpec``-инстансы и
    завершает процесс с кодом 1 при наличии неявного ``action_id``
    (Wave B — переход к обязательной декларации).
    """
    bootstrap()
    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.entrypoints.api.generator.specs import audit_action_specs

    action_list = sorted(action_handler_registry.list_actions())
    for action in action_list:
        typer.echo(f"  {action}")

    typer.echo(f"\nTotal: {len(action_list)} actions")

    explicit, inferred = audit_action_specs()
    typer.echo(f"\nActionSpec audit: explicit={len(explicit)} inferred={len(inferred)}")

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


def services() -> None:
    """Список зарегистрированных сервисов."""
    bootstrap()
    from src.backend.core.svcs_registry import list_services

    names = sorted(list_services())
    for name in names:
        typer.echo(f"  {typer.style(name, fg=typer.colors.GREEN)}")

    total_str = typer.style(
        f"Total: {len(names)} services", fg=typer.colors.BLUE, bold=True
    )
    typer.echo(f"\n{total_str}")


__all__ = ("actions", "routes", "services")
