#!/usr/bin/env python3
"""make onboarding — Typer-based интерактивный onboarding wizard (S42 W2).

Помогает новому разработчику пройти setup проекта end-to-end:
1. Pre-flight checks (Python, git, uv, docker, .venv status).
2. uv sync (или uv sync --all-extras для полного dev).
3. make doctor (health check).
4. Pre-commit hooks install.
5. Опционально: создать sample plugin (codegen_plugin) + sample route.
6. Summary + next steps (документация, FAQ, channel links).

Typer + questionary + rich (паттерн из tools/wizards/plugin_wizard.py).

Запуск:

    # интерактивный wizard
    make onboarding

    # неинтерактивно (для CI / scripted setup)
    make onboarding -- --non-interactive

    # dry-run preview
    make onboarding -- --dry-run
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

__all__ = ("app", "main")

app = typer.Typer(
    name="onboarding",
    help="Интерактивный onboarding wizard для gd_integration_tools.",
    add_completion=False,
)
console = Console()


_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], *, check: bool = True, dry_run: bool = False) -> int:
    """Run subprocess, optional dry-run, return exit code."""
    cmd_str = " ".join(cmd)
    if dry_run:
        console.print(f"  [dim]$ {cmd_str}[/dim] [yellow](dry-run)[/yellow]")
        return 0
    console.print(f"  [dim]$ {cmd_str}[/dim]")
    result = subprocess.run(cmd, cwd=_ROOT)  # noqa: S603
    if check and result.returncode != 0:
        console.print(f"  [red]✗ {cmd[0]} exit={result.returncode}[/red]")
    return result.returncode


def _check_tool(name: str) -> bool:
    """Check if external tool is available."""
    path = shutil.which(name)
    return path is not None


def _step_title(num: int, total: int, title: str) -> None:
    """Print step header with progress."""
    console.print(f"\n[bold cyan]── Step {num}/{total}: {title} ──[/bold cyan]")


def _preflight_checks(dry_run: bool) -> dict[str, bool]:
    """Run pre-flight environment checks.

    Returns dict: tool_name → available.
    """
    _step_title(1, 5, "Pre-flight checks")
    checks: dict[str, bool] = {
        "python": _check_tool("python3") or _check_tool("python"),
        "git": _check_tool("git"),
        "uv": _check_tool("uv"),
        "docker": _check_tool("docker"),
        "make": _check_tool("make"),
    }

    table = Table(title="Environment", show_header=True, header_style="bold")
    table.add_column("Tool", style="cyan")
    table.add_column("Status", justify="center")
    for tool, ok in checks.items():
        status = "[green]✓ OK[/green]" if ok else "[red]✗ missing[/red]"
        table.add_row(tool, status)
    console.print(table)

    # Required tools
    required = ("python", "git", "uv", "make")
    missing_required = [t for t in required if not checks[t]]
    if missing_required:
        console.print(
            f"\n[red]Required tools missing: {', '.join(missing_required)}[/red]"
        )
        if not dry_run:
            console.print(
                "Install: python (apt/brew), git (apt/brew), "
                "uv (https://docs.astral.sh/uv/), make (build-essential)."
            )
            sys.exit(1)
    else:
        console.print("\n[green]✓ All required tools available[/green]")

    return checks


def _install_deps(non_interactive: bool, dry_run: bool) -> None:
    """Step 2: uv sync (or uv sync --all-extras for full dev)."""
    _step_title(2, 5, "Install dependencies (uv sync)")
    extras = "--all-extras" if non_interactive else None
    if not non_interactive and not dry_run:
        want_full = questionary.confirm(
            "Install full dev env (--all-extras, ~500MB) или minimal (--extra dev)?",
            default=False,
        ).ask()
        extras = "--all-extras" if want_full else "--extra dev"

    cmd = ["uv", "sync"]
    if extras:
        cmd.append(extras)
    _run(cmd, dry_run=dry_run)


def _run_doctor(dry_run: bool) -> None:
    """Step 3: make doctor (health check)."""
    _step_title(3, 5, "Health check (make doctor)")
    _run(["make", "doctor"], check=False, dry_run=dry_run)


def _install_precommit(non_interactive: bool, dry_run: bool) -> None:
    """Step 4: pre-commit hooks install."""
    _step_title(4, 5, "Pre-commit hooks (optional)")
    skip = True
    if not non_interactive and not dry_run:
        skip = not questionary.confirm(
            "Install pre-commit hooks? (recommended)", default=True
        ).ask()
    if skip:
        console.print("  [dim]skipped[/dim]")
        return
    _run(["uv", "run", "pre-commit", "install"], dry_run=dry_run)


def _sample_plugin(non_interactive: bool, dry_run: bool) -> None:
    """Step 5: create sample plugin + route (optional)."""
    _step_title(5, 5, "Sample plugin + route (optional)")
    skip = True
    if not non_interactive and not dry_run:
        skip = not questionary.confirm(
            "Create sample plugin ('hello_world') и sample route?", default=False
        ).ask()
    if skip:
        console.print("  [dim]skipped[/dim]")
        return

    if not dry_run:
        name = questionary.text(
            "Plugin name (lowercase, snake_case):",
            default="hello_world",
            validate=lambda t: t.replace("_", "").isalnum() or "Use snake_case",
        ).ask()
        _run(
            ["make", "new-plugin", f"NAME={name}", "FEATURES=ping,echo"],
            dry_run=dry_run,
        )
    else:
        _run(
            ["make", "new-plugin", "NAME=hello_world", "FEATURES=ping,echo"],
            dry_run=dry_run,
        )


def _summary(checks: dict[str, bool]) -> None:
    """Final summary: next steps + links."""
    console.print(
        Panel.fit(
            "[bold green]✓ Onboarding complete![/bold green]\n\n"
            "[bold]Next steps:[/bold]\n"
            "  1. Прочитай [cyan]AGENTS.md[/cyan] и [cyan]PLAN.md[/cyan] (V22+).\n"
            "  2. Посмотри [cyan]docs/tutorials/15_dependency_injection.md[/cyan]\n"
            "     для DI DSL (S40).\n"
            "  3. Попробуй:\n"
            "     • [cyan]make lsp-server[/cyan] (DSL LSP для VS Code)\n"
            "     • [cyan]make doctor[/cyan] (повторный health check)\n"
            "     • [cyan]make test[/cyan] (запустить test suite)\n"
            "  4. Создай свой первый plugin: [cyan]make new-plugin NAME=foo[/cyan]\n"
            "  5. Создай route: [cyan]make wizard-route[/cyan]\n\n"
            "[bold]Каналы:[/bold]\n"
            "  • GitHub: PR/Issues — main repo\n"
            "  • Docs: docs/index.md, docs/tutorials/\n"
            "  • ADR: docs/adr/INDEX.md (62 ADRs)\n",
            title="Welcome to gd_integration_tools",
            border_style="green",
        )
    )


@app.command()
def main(
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive", help="Non-interactive mode (для CI / scripted setup)."
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print commands без execution.")
    ] = False,
) -> None:
    """Onboarding wizard: setup dev environment end-to-end."""
    if not non_interactive and not dry_run:
        console.print(
            Panel.fit(
                "[bold]gd_integration_tools — Onboarding Wizard[/bold]\n\n"
                "Пройдём setup по 5 шагам (~2-3 минуты).\n"
                "Большинство шагов опциональны — wizard спросит.\n",
                border_style="cyan",
            )
        )

    # Step 1: pre-flight
    checks = _preflight_checks(dry_run)

    # Step 2: install deps
    _install_deps(non_interactive, dry_run)

    # Step 3: doctor
    _run_doctor(dry_run)

    # Step 4: pre-commit
    _install_precommit(non_interactive, dry_run)

    # Step 5: sample plugin
    _sample_plugin(non_interactive, dry_run)

    # Summary
    if not dry_run:
        _summary(checks)
    else:
        console.print("\n[yellow]dry-run: skipped summary[/yellow]")


if __name__ == "__main__":
    app()
