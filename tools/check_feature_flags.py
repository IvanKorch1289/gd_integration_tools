#!/usr/bin/env python3
"""Аудит ``src/backend/core/config/features.py`` (K10 Sprint 2 platform gate).

S59 W1 (libraries > custom, v22 п.5): мигрирован с ``argparse`` на
``typer`` + ``rich`` (template — ``check_layer_imports`` в S58 W2).

Назначение:
    Проверяет default-OFF политику реестра feature-flag:
    - все поля FeatureFlags имеют default=False;
    - все поля имеют непустой description (audit-комментарий);
    - все поля имеют title.

При нарушениях — exit 1. Используется в pre-commit и CI gate.

Запуск::

    python tools/check_feature_flags.py [--allow-non-off NAME1,NAME2]
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console

try:
    from src.backend.core.config.features import FeatureFlags
except ImportError as exc:
    print(f"✗ Импорт FeatureFlags провалился: {exc}", file=sys.stderr)
    sys.exit(2)

app = typer.Typer(
    name="check_feature_flags",
    help="Audit FeatureFlags registry: default-OFF policy + description + title.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
console_err = Console(stderr=True, style="red")


def _audit(allow_non_off: set[str]) -> list[str]:
    """Возвращает список ошибок аудита (пустой → всё ОК)."""
    errors: list[str] = []
    for name, field in FeatureFlags.model_fields.items():
        if field.default is not False and name not in allow_non_off:
            errors.append(
                f"feature_flags.{name}: default={field.default!r}, "
                f"должен быть False (default-OFF policy). "
                f"Если намеренно — добавить в --allow-non-off."
            )
        if not field.description:
            errors.append(
                f"feature_flags.{name}: отсутствует description "
                f"(audit-комментарий с owner/ETA обязателен)."
            )
        if not field.title:
            errors.append(f"feature_flags.{name}: отсутствует title.")
    return errors


@app.command()
def main(
    allow_non_off: str = typer.Option(
        "",
        "--allow-non-off",
        help="Список flag-name через запятую, которые разрешено иметь "
        "default!=False (исключения из default-OFF policy).",
    ),
) -> None:
    """CLI-entrypoint (typer)."""
    allow = {n.strip() for n in allow_non_off.split(",") if n.strip()}
    errors = _audit(allow)

    if errors:
        console_err.print(
            f"[bold red]✗ feature-flag audit FAILED:[/bold red] {len(errors)} нарушений"
        )
        for err in errors:
            console_err.print(f"  [red]-[/red] {err}")
        raise typer.Exit(1)

    total = len(FeatureFlags.model_fields)
    console.print(
        f"[bold green]✓[/bold green] feature-flag audit OK: {total} flag, "
        f"все default-OFF, все имеют title + description."
    )
    raise typer.Exit(0)


if __name__ == "__main__":
    app()
