#!/usr/bin/env python3
"""Typer-based Rich CLI for developer experience (GAP-DX-1 S35).

Provides subcommands to manage routes, workflows, cache, and agents
via the admin REST API on localhost:8000.

Usage:
    python tools/cli.py --help
    python tools/cli.py route list
    python tools/cli.py workflow list --status pending
    python tools/cli.py cache stats
    python tools/cli.py agent list-tools
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

__version__ = "1.0.0"

BASE_URL = "http://localhost:8000/api/v1/admin"
TIMEOUT = 30.0

console = Console()

# ─── HTTP Client Helpers ────────────────────────────────────────────────────


def _get(path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET request to admin API (synchronous)."""
    with httpx.Client(timeout=TIMEOUT) as client:
        url = f"{BASE_URL}{path}"
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def _post(
    path: str,
    json_data: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """POST request to admin API (synchronous)."""
    with httpx.Client(timeout=TIMEOUT) as client:
        url = f"{BASE_URL}{path}"
        response = client.post(url, json=json_data, params=params)
        response.raise_for_status()
        return response.json()


def _delete(path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """DELETE request to admin API (synchronous)."""
    with httpx.Client(timeout=TIMEOUT) as client:
        url = f"{BASE_URL}{path}"
        response = client.delete(url, params=params)
        response.raise_for_status()
        return response.json()


def _handle_error(exc: Exception) -> None:
    """Print error and exit."""
    console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(code=1)


# ─── App Setup ─────────────────────────────────────────────────────────────

app = typer.Typer(
    name="gd-cli",
    help="Rich CLI for gd_integration_tools admin operations",
    add_completion=False,
    invoke_without_command=True,
)

route_app = typer.Typer(help="Manage DSL routes")
workflow_app = typer.Typer(help="Manage durable workflows")
cache_app = typer.Typer(help="Manage cache")
agent_app = typer.Typer(help="Manage agents and tools")

app.add_typer(route_app, name="route")
app.add_typer(workflow_app, name="workflow")
app.add_typer(cache_app, name="cache")
app.add_typer(agent_app, name="agent")


@app.callback()
def main() -> None:
    """gd_integration_tools Rich CLI - type --help for more information."""
    pass


# ─── Route Subcommands ─────────────────────────────────────────────────────


@route_app.command(
    "list", help="List all DSL routes with their status and feature flags"
)
def route_list() -> None:
    """List all registered DSL routes."""
    try:
        data = _get("/routes")
        routes = data.get("routes", [])
        total = data.get("total", len(routes))

        table = Table(title=f"DSL Routes (total: {total})")
        table.add_column("Route ID", style="cyan")
        table.add_column("Enabled", style="green")
        table.add_column("Feature Flag", style="yellow")

        for r in routes:
            table.add_row(
                r.get("route_id", ""),
                "✓" if r.get("enabled") else "✗",
                r.get("feature_flag", ""),
            )

        console.print(table)
    except Exception as exc:
        _handle_error(exc)


@route_app.command("validate", help="Validate a route by path")
def route_validate(
    route_path: str = typer.Argument(..., help="Route path to validate"),
) -> None:
    """Validate a specific route exists."""
    try:
        data = _get("/routes")
        routes = data.get("routes", [])
        found = [r for r in routes if r.get("route_id") == route_path]
        if found:
            console.print(f"[green]Route '{route_path}' is valid[/green]")
        else:
            console.print(f"[yellow]Route '{route_path}' not found[/yellow]")
    except Exception as exc:
        _handle_error(exc)


@route_app.command("start", help="Enable a route by path")
def route_start(
    route_path: str = typer.Argument(..., help="Route path to enable"),
) -> None:
    """Enable a route."""
    try:
        result = _post(
            "/routes/toggle", params={"route_path": route_path, "enable": "true"}
        )
        console.print(f"[green]Route '{route_path}' enabled: {result}[/green]")
    except Exception as exc:
        _handle_error(exc)


@route_app.command("stop", help="Disable a route by path")
def route_stop(
    route_path: str = typer.Argument(..., help="Route path to disable"),
) -> None:
    """Disable a route."""
    try:
        result = _post(
            "/routes/toggle", params={"route_path": route_path, "enable": "false"}
        )
        console.print(f"[yellow]Route '{route_path}' disabled: {result}[/yellow]")
    except Exception as exc:
        _handle_error(exc)


# ─── Workflow Subcommands ─────────────────────────────────────────────────


@workflow_app.command(
    "list", help="List durable workflow instances with optional filtering"
)
def workflow_list(
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status (pending/running/paused/succeeded/failed/cancelled)",
    ),
    workflow_name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Filter by workflow name"
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Max results to return"),
) -> None:
    """List workflow instances."""
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    if workflow_name:
        params["workflow_name"] = workflow_name

    try:
        data = _get("/workflows", params=params)
        instances: list[dict[str, Any]] = data if isinstance(data, list) else []

        table = Table(title="Workflow Instances")
        table.add_column("ID", style="cyan")
        table.add_column("Workflow Name", style="magenta")
        table.add_column("Status", style="yellow")
        table.add_column("Created At", style="dim")

        for inst in instances:
            table.add_row(
                str(inst.get("id", ""))[:8],
                inst.get("workflow_name", ""),
                inst.get("status", ""),
                str(inst.get("created_at", ""))[:19],
            )

        console.print(table)
    except Exception as exc:
        _handle_error(exc)


@workflow_app.command("pause", help="Pause a workflow instance by ID")
def workflow_pause(
    instance_id: str = typer.Argument(..., help="Workflow instance UUID"),
) -> None:
    """Pause a workflow instance (not directly supported; use cancel)."""
    console.print(
        "[yellow]Pause is not directly exposed. Use 'cancel' for graceful cancellation.[/yellow]"
    )


@workflow_app.command("resume", help="Resume a paused workflow instance")
def workflow_resume(
    instance_id: str = typer.Argument(..., help="Workflow instance UUID"),
) -> None:
    """Resume a paused workflow."""
    try:
        result = _post(f"/workflows/{instance_id}/resume")
        console.print(f"[green]Workflow {instance_id} resumed: {result}[/green]")
    except Exception as exc:
        _handle_error(exc)


@workflow_app.command("cancel", help="Cancel a workflow instance gracefully")
def workflow_cancel(
    instance_id: str = typer.Argument(..., help="Workflow instance UUID"),
    reason: Optional[str] = typer.Option(
        None, "--reason", "-r", help="Cancellation reason"
    ),
) -> None:
    """Cancel a workflow instance."""
    json_data: dict[str, Any] = {}
    if reason:
        json_data["reason"] = reason

    try:
        result = _post(
            f"/workflows/{instance_id}/cancel",
            json_data=json_data if json_data else None,
        )
        console.print(
            f"[yellow]Workflow {instance_id} cancellation requested: {result}[/yellow]"
        )
    except Exception as exc:
        _handle_error(exc)


# ─── Cache Subcommands ─────────────────────────────────────────────────────


@cache_app.command("stats", help="Show cache hit/miss metrics for all tiers")
def cache_stats() -> None:
    """Show cache statistics."""
    try:
        data = _get("/cache/stats")

        table = Table(title="Cache Statistics")
        table.add_column("Tier", style="cyan")
        table.add_column("Hits", style="green")
        table.add_column("Misses", style="yellow")
        table.add_column("Hit Rate", style="magenta")

        tiers = data if isinstance(data, dict) else {}
        for tier, stats in tiers.items():
            hits = stats.get("hits", 0)
            misses = stats.get("misses", 0)
            total = hits + misses
            rate = (hits / total * 100) if total > 0 else 0
            table.add_row(tier, str(hits), str(misses), f"{rate:.1f}%")

        console.print(table)
    except Exception as exc:
        _handle_error(exc)


@cache_app.command("flush", help="Flush all cache entries")
def cache_flush() -> None:
    """Flush entire cache."""
    try:
        result = _delete("/cache/invalidate")
        console.print(f"[green]Cache flushed: {result}[/green]")
    except Exception as exc:
        _handle_error(exc)


@cache_app.command(
    "invalidate-pattern", help="Invalidate cache entries matching a glob pattern"
)
def cache_invalidate_pattern(
    pattern: str = typer.Argument(..., help="Glob pattern (e.g., 'entity:orders:*')"),
) -> None:
    """Invalidate cache by pattern."""
    try:
        result = _delete("/cache/invalidate/pattern", params={"pattern": pattern})
        removed = result.get("removed", 0)
        console.print(
            f"[green]Invalidated {removed} keys matching pattern '{pattern}'[/green]"
        )
    except Exception as exc:
        _handle_error(exc)


@cache_app.command("invalidate-tag", help="Invalidate cache entries by tag(s)")
def cache_invalidate_tag(
    tags: list[str] = typer.Argument(
        ..., help="Tag(s) to invalidate (e.g., 'entity:orders' 'table:orders')"
    ),
) -> None:
    """Invalidate cache by tag."""
    try:
        tags_param = ",".join(tags)
        result = _delete("/cache/invalidate/tags", params={"tags": tags_param})
        removed = result.get("removed", 0)
        console.print(f"[green]Invalidated {removed} keys with tags: {tags}[/green]")
    except Exception as exc:
        _handle_error(exc)


# ─── Agent Subcommands ─────────────────────────────────────────────────────


@agent_app.command("list-tools", help="List all registered agent tools")
def agent_list_tools() -> None:
    """List all registered agent tools."""
    try:
        data = _get("/actions")
        actions = data.get("actions", [])

        table = Table(title=f"Agent Tools (total: {len(actions)})")
        table.add_column("Namespace", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Description", style="dim")
        table.add_column("Tier", style="yellow")

        for action in actions:
            table.add_row(
                action.get("namespace", ""),
                action.get("name", ""),
                action.get("description", ""),
                action.get("tier", ""),
            )

        console.print(table)
    except Exception as exc:
        _handle_error(exc)


@agent_app.command("invoke-tool", help="Invoke a registered agent tool by name")
def agent_invoke_tool(
    name: str = typer.Argument(..., help="Name of the tool to invoke"),
    payload: Optional[str] = typer.Option(
        None, "--payload", "-p", help="JSON payload for the tool"
    ),
) -> None:
    """Invoke an agent tool."""
    json_data: dict[str, Any] = {"name": name}
    if payload:
        try:
            json_data["payload"] = json.loads(payload)
        except json.JSONDecodeError:
            console.print("[red]Invalid JSON payload[/red]")
            raise typer.Exit(code=1)

    try:
        result = _post("/actions/invoke", json_data=json_data)
        console.print(f"[green]Tool '{name}' invoked successfully[/green]")
        console.print_json(data=result)
    except Exception as exc:
        _handle_error(exc)


if __name__ == "__main__":
    app()
