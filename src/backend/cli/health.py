"""Health introspection commands для ``manage.py``.

P1 CLI decomposition W3 (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability. ``health`` + ``breakers`` — read-only
introspection, нет side effects.

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py health`` — OK/FAIL каждого компонента (redis, db).
- ``python manage.py breakers`` — состояние circuit breakers.

NOT @app.command() decorated здесь — manage.py imports + decorates для
сохранения CLI contract (top-level команды).

Diagnostic command (``diagnose``) ОСТАЁТСЯ в manage.py — он big enough
(140 LOC, multi-domain aggregates) для отдельной wave — W4 candidate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from src.backend.cli._bootstrap import bootstrap

if TYPE_CHECKING:
    pass


def health() -> None:
    """Проверка здоровья всех компонентов."""
    import asyncio

    bootstrap()

    async def _check() -> dict[str, bool]:
        checks: dict[str, bool] = {}
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


def breakers() -> None:
    """Состояние circuit breakers."""
    from src.backend.infrastructure.clients.external.circuit_breakers import (
        breaker_registry,
    )

    for info in breaker_registry.get_all_status():
        state = info["state"]
        color = typer.colors.GREEN if state == "closed" else typer.colors.RED
        typer.echo(
            f"  {info['name']:<20} {typer.style(state, fg=color)} "
            f"(failures: {info['failure_count']})"
        )


__all__ = ("breakers", "health")
