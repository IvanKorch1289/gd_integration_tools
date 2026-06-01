#!/usr/bin/env python3
"""make wizard-route — Typer-based interactive CLI для создания DSL routes (S33 W1).

Генерирует ``routes/<name>/route.toml`` + ``main.dsl.yaml``.
Интеграция: ``make wizard-route``.

Запуск:

    # интерактивный wizard
    python tools/wizards/route_wizard.py

    # неинтерактивно (CLI)
    python tools/wizards/route_wizard.py --name credit_check --source http --sink http

    # dry-run preview
    python tools/wizards/route_wizard.py --name credit_check --source http --sink http --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

ROOT = Path(__file__).resolve().parents[2]
ROUTES_DIR = ROOT / "routes"

SOURCE_DESCRIPTIONS: dict[str, str] = {
    "http": "HTTP endpoint (REST/webhook-style)",
    "cron": "Cron scheduler (APScheduler cron-style)",
    "kafka": "Kafka consumer (topic + group_id)",
    "webhook": "Webhook receiver (path-based)",
    "file_watch": "File watcher (glob pattern)",
    "cdc": "CDC source (database change data capture)",
}

SINK_DESCRIPTIONS: dict[str, str] = {
    "http": "HTTP sink (http_call step)",
    "kafka": "Kafka producer (topic publish)",
    "db": "Database sink (crud_create step)",
    "file": "File sink (write to path)",
    "dlq": "Dead Letter Queue (dlq sink)",
    "log": "Log sink (structured log output)",
}

console = Console()


def _validate_name(name: str) -> str:
    """Валидация snake_case имени route."""
    if not name:
        raise typer.Exit(code=1)
    if "-" in name:
        raise typer.Abort(f"Route name must be snake_case (no dashes): {name!r}")
    if not name.replace("_", "").isalnum():
        raise typer.Abort(f"Route name must contain only a-z, 0-9, _: {name!r}")
    return name


def _route_dir(name: str) -> Path:
    return ROUTES_DIR / name


def _route_exists(name: str) -> bool:
    return _route_dir(name).exists()


def _source_yaml(source: str) -> dict[str, object]:
    """Build source section for DSL YAML."""
    if source == "http":
        return {"http": {"method": "POST", "path": "/api/v1/CHANGEME"}}
    if source == "cron":
        return {"cron": "0 */6 * * *"}
    if source == "kafka":
        return {"kafka": {"topic": "CHANGEME", "group_id": "CHANGEME"}}
    if source == "webhook":
        return {"webhook": {"path": "/webhooks/CHANGEME"}}
    if source == "file_watch":
        return {"file_watch": {"glob": "/data/incoming/*.csv"}}
    if source == "cdc":
        return {"cdc": {"table": "public.CHANGEME"}}
    return {source: "TODO"}


def _sink_step(sink: str) -> dict[str, object]:
    """Build sink step for DSL YAML."""
    if sink == "http":
        return {"http_call": {"url": "https://api.test/sink", "method": "POST"}}
    if sink == "kafka":
        return {"sink_publish": {"sink_kind": "kafka", "topic": "CHANGEME"}}
    if sink == "db":
        return {"crud_create": {"entity": "CHANGEME", "body": "${body}"}}
    if sink == "file":
        return {"sink_publish": {"sink_kind": "file", "path": "/data/out/$id.json"}}
    if sink == "dlq":
        return {"sink_publish": {"sink_kind": "dlq", "queue": "default_dlq"}}
    return {"log": {"level": "info"}}


def _build_toml(
    name: str,
    *,
    ai: bool,
    retry: bool,
    tenant_aware: bool,
    p95_ms: int,
    timeout_ms: int,
) -> str:
    capabilities = ["net.outbound", "db.write", "audit.write"]
    if ai:
        capabilities.append("ai.llm")
    if retry:
        capabilities.append("retry.enabled")
    cap_str = "[" + ", ".join(f'"{c}"' for c in capabilities) + "]"

    return f"""\
# route.toml (V11): manifest for route '{name}' (S33 W1 wizard).
name = "{name}"
version = "0.1.0"
requires_core = ">=22.0,<23"
capabilities = {cap_str}
tenant_aware = {str(tenant_aware).lower()}
feature_flag = {{ enabled = true, gate = "{name}_enabled" }}
slo = {{ p95_ms = {p95_ms}, timeout_ms = {timeout_ms} }}
schedule = "never"

[feature_flags]
default = ["default"]
"""


def _build_yaml(
    name: str,
    source: str,
    sink: str,
    *,
    ai: bool = False,
    retry: bool = False,
    retry_attempts: int = 3,
    ai_model: str = "claude-3-5-sonnet-20241022",
    ai_provider: str = "claude",
) -> str:
    import yaml

    steps: list[dict[str, object]] = []
    steps.append(
        {"call_function": {"ref": f"extensions.{name}.normalizer:apply_rules"}}
    )

    if retry:
        steps.append(
            {
                "policy": {
                    "retry": {
                        "attempts": retry_attempts,
                        "backoff": "exponential",
                        "max_delay_ms": 5000,
                    }
                }
            }
        )

    if ai:
        steps.append(
            {
                "llm_call": {
                    "provider": ai_provider,
                    "model": ai_model,
                    "prompt_from": "body.context",
                    "result_property": "ai_response",
                    "dry_run_provider": "mock-llm",
                }
            }
        )

    steps.append(_sink_step(sink))
    steps.append({"audit": {"action": f"{name}.processed"}})
    steps.append({"to": {"response": {"code": 200, "body": "${body}"}}})

    route = {"route_id": name, "source": _source_yaml(source), "steps": steps}

    return yaml.safe_dump(route, allow_unicode=True, sort_keys=False)


def _preview(name: str, source: str, sink: str, *, ai: bool, retry: bool) -> None:
    """Print diff preview in rich."""
    toml_content = _build_toml(
        name, ai=ai, retry=retry, tenant_aware=True, p95_ms=500, timeout_ms=5000
    )
    yaml_content = _build_yaml(name, source, sink, ai=ai, retry=retry, retry_attempts=3)

    toml_syntax = Syntax(toml_content, "toml", theme="monokai", line_numbers=True)
    yaml_syntax = Syntax(yaml_content, "yaml", theme="monokai", line_numbers=True)

    console.print(Panel(toml_syntax, title=f"routes/{name}/route.toml", expand=False))
    console.print(
        Panel(yaml_syntax, title=f"routes/{name}/main.dsl.yaml", expand=False)
    )


def _write_scaffold(
    name: str,
    source: str,
    sink: str,
    *,
    ai: bool = False,
    retry: bool = False,
    retry_attempts: int = 3,
    ai_model: str = "claude-3-5-sonnet-20241022",
    ai_provider: str = "claude",
    tenant_aware: bool = True,
    p95_ms: int = 500,
    timeout_ms: int = 5000,
    force: bool = False,
) -> Path:
    """Write route.toml + main.dsl.yaml. Returns path to directory."""
    target = _route_dir(name)
    if target.exists() and not force:
        raise FileExistsError(
            f"Directory already exists: {target}. Use --force to overwrite."
        )
    target.mkdir(parents=True, exist_ok=True)

    toml_content = _build_toml(
        name,
        ai=ai,
        retry=retry,
        tenant_aware=tenant_aware,
        p95_ms=p95_ms,
        timeout_ms=timeout_ms,
    )
    yaml_content = _build_yaml(
        name,
        source,
        sink,
        ai=ai,
        retry=retry,
        retry_attempts=retry_attempts,
        ai_model=ai_model,
        ai_provider=ai_provider,
    )

    (target / "route.toml").write_text(toml_content, encoding="utf-8")
    (target / "main.dsl.yaml").write_text(yaml_content, encoding="utf-8")
    return target


# ─── Typer app ────────────────────────────────────────────────────────────────

app = typer.Typer(name="wizard-route", help=__doc__, add_completion=False)

dry_run_option = typer.Option(
    False, "--dry-run", help="Show diff without writing files"
)
force_option = typer.Option(False, "--force", help="Overwrite existing directory")
routes_dir_option = typer.Option(ROUTES_DIR, "--routes-dir", help="Routes directory")


@app.command()
def cli(
    ctx: typer.Context,
    name: Annotated[
        Optional[str], typer.Option("--name", help="snake_case route name")
    ] = None,
    source: Annotated[
        Optional[str], typer.Option("--source", help="Source type")
    ] = None,
    sink: Annotated[Optional[str], typer.Option("--sink", help="Sink type")] = None,
    ai: bool = False,
    retry: bool = False,
    retry_attempts: int = 3,
    ai_model: str = "claude-3-5-sonnet-20241022",
    ai_provider: str = "claude",
    tenant_aware: bool = True,
    p95_ms: int = 500,
    timeout_ms: int = 5000,
    dry_run: bool = dry_run_option,
    force: bool = force_option,
    routes_dir: Path = routes_dir_option,
) -> None:
    """Interactive wizard for creating a new DSL route."""

    global ROUTES_DIR
    if routes_dir and routes_dir != ROUTES_DIR:
        ROUTES_DIR = routes_dir

    is_interactive = sys.stdin.isatty() and name is None

    # ── Interactive mode ───────────────────────────────────────────────────
    if is_interactive:
        console.print("[bold cyan]== Route Wizard (S33 W1) ==[/bold cyan]")

        name = questionary.text(
            "Route name (snake_case, e.g. credit_check):", validate=_validate_name
        ).ask()
        if not name:
            raise typer.Abort()

        if _route_exists(name) and not force:
            console.print(
                f"[yellow]Warning: routes/{name} already exists. Use --force to overwrite.[/yellow]"
            )
            raise typer.Exit(code=0)

        # Source selection
        source = questionary.select(
            "Source:", choices=list(SOURCE_DESCRIPTIONS.keys())
        ).ask()
        console.print(f"  -> {SOURCE_DESCRIPTIONS[source]}")

        # Sink selection
        sink = questionary.select("Sink:", choices=list(SINK_DESCRIPTIONS.keys())).ask()
        console.print(f"  -> {SINK_DESCRIPTIONS[sink]}")

        # SLO
        p95_str = questionary.text("SLO p95_ms:", default="500").ask()
        p95_ms = int(p95_str) if p95_str and p95_str.isdigit() else 500

        timeout_str = questionary.text("SLO timeout_ms:", default="5000").ask()
        timeout_ms = int(timeout_str) if timeout_str and timeout_str.isdigit() else 5000

        # Tenant awareness
        tenant_aware = questionary.confirm("Tenant-aware route?", default=True).ask()

        # Retry policy
        retry = questionary.confirm("Add retry policy?", default=False).ask()

        # AI step
        _ai = questionary.confirm("Add AI (llm_call) step?", default=False).ask()
        _ai_model = ai_model
        _ai_provider = ai_provider
        if _ai:
            _ai_provider = questionary.select(
                "AI Provider:", choices=["claude", "openai", "gemini", "mock-llm"]
            ).ask()
            _ai_model = (
                questionary.text(
                    "AI Model:", default="claude-3-5-sonnet-20241022"
                ).ask()
                or _ai_model
            )

        console.print("[bold cyan]== Preview ==[/bold cyan]")
        _preview(name, source, sink, ai=_ai, retry=retry)

        confirm_write = questionary.confirm("Create files?", default=True).ask()
        if not confirm_write:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(code=0)

        try:
            target = _write_scaffold(
                name,
                source,
                sink,
                ai=_ai,
                retry=retry,
                retry_attempts=retry_attempts,
                ai_model=_ai_model,
                ai_provider=_ai_provider,
                tenant_aware=tenant_aware,
                p95_ms=p95_ms,
                timeout_ms=timeout_ms,
                force=force,
            )
        except FileExistsError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)

        console.print(f"[green]OK: Route created at {target}[/green]")
        console.print(f"  -> {target / 'route.toml'}")
        console.print(f"  -> {target / 'main.dsl.yaml'}")
        return

    # ── Non-interactive mode (CLI) ────────────────────────────────────────────
    if not name:
        console.print("[red]Error: --name is required in non-interactive mode[/red]")
        raise typer.Exit(code=1)

    try:
        _validate_name(name)
    except typer.Abort:
        raise

    source = source or "http"
    sink = sink or "http"

    if source not in SOURCE_DESCRIPTIONS:
        console.print(f"[red]Unknown source: {source!r}[/red]")
        raise typer.Exit(code=1)
    if sink not in SINK_DESCRIPTIONS:
        console.print(f"[red]Unknown sink: {sink!r}[/red]")
        raise typer.Exit(code=1)

    if _route_exists(name) and not force:
        console.print(
            f"[red]Directory routes/{name} already exists. Use --force.[/red]"
        )
        raise typer.Exit(code=1)

    # ── Dry-run ───────────────────────────────────────────────────────────────
    if dry_run:
        console.print(f"\n[bold]Dry-run: routes/{name}[/bold]\n")
        _preview(name, source, sink, ai=ai, retry=retry)
        raise typer.Exit(code=0)

    # ── Write files ───────────────────────────────────────────────────────────
    try:
        target = _write_scaffold(
            name,
            source,
            sink,
            ai=ai,
            retry=retry,
            retry_attempts=retry_attempts,
            ai_model=ai_model,
            ai_provider=ai_provider,
            tenant_aware=tenant_aware,
            p95_ms=p95_ms,
            timeout_ms=timeout_ms,
            force=force,
        )
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]OK: Route created at {target}[/green]")
    console.print(f"  -> {target / 'route.toml'}")
    console.print(f"  -> {target / 'main.dsl.yaml'}")


if __name__ == "__main__":
    app()
