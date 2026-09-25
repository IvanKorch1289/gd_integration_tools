"""Completions sub-app для ``manage.py``.

P1 CLI decomposition W10 (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability. ``completions`` — Typer sub-app с 1
subcommand для shell completions (install).

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py completions install --shell bash|zsh|fish|powershell|pwsh``
  — install shell completions.

Typer sub-app pattern (consistent с W5/W6/W8/W9/W10 ai-eval):
- ``completions_app = typer.Typer(help="Install shell completions for gd-tools CLI")``
- ``app.add_typer(completions_app, name="completions")`` в manage.py
- Команды регистрируются через ``@completions_app.command("name")``
"""

from __future__ import annotations

import typer

completions_app = typer.Typer(help="Install shell completions for gd-tools CLI")


@completions_app.command("install")
def completions_install(
    shell: str = typer.Option(
        ..., "--shell", "-s", help="Shell type: bash | zsh | fish | powershell"
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

    # Get the underlying Click command and install completions.
    # Lazy-import manage.py to avoid circular import (manage.py imports
    # this module via ``from src.backend.cli.completions import completions_app``).

    # Late-bind app reference at runtime (after manage.py module load complete).
    import sys

    _manage_mod = sys.modules.get("__main__") or sys.modules.get("manage")
    if _manage_mod is None or not hasattr(_manage_mod, "app"):
        typer.echo(
            "ERR: cannot access manage.app for completion generation. "
            "Run this command via 'python manage.py completions install'.",
            err=True,
        )
        raise typer.Exit(code=1)
    click_cmd = typer_main.get_command(_manage_mod.app)
    prog_name = click_cmd.info_name or "gd-tools"  # type: ignore[attr-defined]
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


__all__ = ("completions_app",)
