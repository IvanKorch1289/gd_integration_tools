"""Diagnose command для ``manage.py``.

P1 CLI decomposition W4 (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability. ``diagnose`` — multi-domain aggregate
introspection (140 LOC), собирает health/breakers/services/routes/actions/
feature flags в один отчёт для CI pipeline.

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py diagnose [--json] [--verbose]`` —
  aggregate diagnostics + JSON output для CI.

NOT @app.command() decorated здесь — manage.py imports + decorates для
сохранения CLI contract (top-level команда).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

from src.backend.cli._bootstrap import (
    bootstrap,  # type: ignore[import-not-found,attr-defined]
)

if TYPE_CHECKING:
    pass


def diagnose(
    json_output: bool = typer.Option(
        False, "--json", help="Output as JSON for CI/automation"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Include feature flags and full routes"
    ),
) -> None:
    """Sprint 19 K2 W2 + K5 W4: Aggregate all diagnostics into JSON for CI pipeline.

    Wave k2-w2 was delivered as part of k5-w4-quick-wins-pack (d82cfbd6).
    This command collects: health checks, circuit breakers, services, routes count,
    actions count, feature flags status, Python/version info.
    Use --json for machine-readable output.
    """
    import asyncio
    import json as _json
    import platform
    import sys

    bootstrap()

    async def _check_async() -> dict[str, bool]:
        checks: dict[str, bool] = {}
        try:
            from src.backend.infrastructure.clients.storage.redis import (
                redis_client,  # type: ignore[import-not-found,attr-defined]
            )

            checks["redis"] = await redis_client.check_connection()
        except Exception:
            checks["redis"] = False

        try:
            from src.backend.infrastructure.database.database import (
                db_initializer,  # type: ignore[import-not-found,attr-defined]
            )

            checks["database"] = await db_initializer.check_connection()
        except Exception:
            checks["database"] = False

        return checks

    # Gather all diagnostics synchronously where possible
    diagnostics: dict[str, Any] = {
        "version": {"python": sys.version, "platform": platform.platform()},
        "health": asyncio.run(_check_async()),
        "breakers": [],
        "services": [],
        "routes_count": 0,
        "actions_count": 0,
        "feature_flags": {},
    }

    # Circuit breakers
    try:
        from src.backend.infrastructure.clients.external.circuit_breakers import (  # type: ignore[import-not-found]
            breaker_registry,
        )

        diagnostics["breakers"] = breaker_registry.get_all_status()  # type: ignore[attr-defined]
    except Exception:  # noqa: S110  # silent fallback (best-effort cleanup, non-critical)
        pass

    # Services
    try:
        from src.backend.core.svcs_registry import (
            list_services,  # type: ignore[import-not-found,attr-defined]
        )

        diagnostics["services"] = sorted(list_services())
    except Exception:  # noqa: S110  # silent fallback (best-effort cleanup, non-critical)
        pass

    # Routes count
    #
    # Раньше здесь был код вида ``from src.backend.dsl.route.loader import
    # RouteLoader`` + ``RouteLoader.load_all()``. Оба обращения неверны:
    # модуля ``src.backend.dsl.route`` в проекте нет (реальный путь —
    # ``src.backend.services.routes.loader``), а у ``RouteLoader`` есть только
    # ``discover_and_load()`` — async-метод с побочными эффектами (декларация
    # capability, регистрация pipeline). Всё это было завёрнуто в
    # ``except Exception: pass``, поэтому ``diagnostics["routes_count"]``
    # НИКОГДА не заполнялся — диагностика молча врала.
    #
    # Диагностика не должна мутировать состояние, поэтому здесь только
    # разбор манифестов с диска, без регистрации.
    try:
        from src.backend.core.config.config_loader import repo_root
        from src.backend.services.routes.manifest_toml import (
            RouteManifestError,
            load_route_manifest,
        )

        routes_dir = repo_root() / "routes"
        manifests = sorted(routes_dir.glob("*/route.toml"))
        diagnostics["routes_dir"] = str(routes_dir)
        diagnostics["routes_count"] = len(manifests)
        parsed: list[dict[str, str]] = []
        invalid: list[str] = []
        for manifest_path in manifests:
            try:
                manifest = load_route_manifest(manifest_path)
            except RouteManifestError as exc:
                invalid.append(f"{manifest_path.parent.name}: {exc}")
                continue
            parsed.append(
                {
                    "name": manifest.name,
                    "version": manifest.version,
                    "pipelines": ",".join(manifest.pipelines),
                }
            )
        diagnostics["routes_valid"] = len(parsed)
        if invalid:
            diagnostics["routes_invalid"] = invalid
        if verbose:
            diagnostics["routes"] = parsed
    except Exception as exc:  # noqa: BLE001 — best-effort, но причина видна
        diagnostics["routes_error"] = f"{type(exc).__name__}: {exc}"

    # Actions count
    try:
        from src.backend.core.actions import (  # type: ignore[import-not-found,attr-defined]
            ActionHandlerRegistry,  # type: ignore[attr-defined]
        )

        diagnostics["actions_count"] = len(ActionHandlerRegistry.get_all_actions())
    except Exception:  # noqa: S110  # silent fallback (best-effort cleanup, non-critical)
        pass

    # Feature flags
    try:
        from src.backend.core.config.features import (
            feature_flags,  # type: ignore[import-not-found,attr-defined]
        )

        flags = feature_flags.model_dump()
        if not verbose:
            # In non-verbose mode, only show flags that are ON
            flags = {k: v for k, v in flags.items() if v}
        diagnostics["feature_flags"] = flags
    except Exception:  # noqa: S110  # silent fallback (best-effort cleanup, non-critical)
        pass

    if json_output:
        typer.echo(_json.dumps(diagnostics, indent=2, default=str))
    else:
        # Human-readable summary
        typer.echo("=== GD Integration Tools Diagnostic Report ===")
        typer.echo(f"Python: {sys.version.split()[0]}")
        typer.echo(f"Platform: {platform.platform()}")
        typer.echo("")
        typer.echo("Health:")
        for name, ok in diagnostics["health"].items():  # type: ignore[attr-defined]
            status = (
                typer.style("OK", fg=typer.colors.GREEN)
                if ok
                else typer.style("FAIL", fg=typer.colors.RED)
            )
            typer.echo(f"  {name:<20} {status}")
        typer.echo("")
        typer.echo(f"Circuit Breakers: {len(diagnostics['breakers'])}")
        for b in diagnostics["breakers"]:  # type: ignore[attr-defined]
            state = b["state"]
            color = typer.colors.GREEN if state == "closed" else typer.colors.RED
            typer.echo(f"  {b['name']:<30} {typer.style(state, fg=color)}")
        typer.echo("")
        typer.echo(f"Services: {len(diagnostics['services'])}")
        typer.echo(f"Routes: {diagnostics['routes_count']}")
        typer.echo(f"Actions: {diagnostics['actions_count']}")
        typer.echo(f"Feature Flags (ON): {len(diagnostics['feature_flags'])}")
        if verbose and diagnostics.get("routes"):
            typer.echo("")
            typer.echo("Routes:")
            for r in diagnostics["routes"]:
                typer.echo(f"  {r['name']} ({r['source']})")


__all__ = ("diagnose",)
