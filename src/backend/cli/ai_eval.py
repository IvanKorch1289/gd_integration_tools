"""AI eval sub-app для ``manage.py``.

P1 CLI decomposition W10 (v4 §10 P1, 2026-09-24): извлечено из
``manage.py`` для bounded maintainability. ``ai-eval`` — Typer sub-app
с 2 subcommands для Inspect AI nightly suites (nightly + suite).

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py ai-eval nightly [--artifacts-dir <path>]`` —
  все reference Inspect AI suite + report.
- ``python manage.py ai-eval suite <name> [--artifacts-dir <path>]`` —
  один suite по имени (для local debugging).

Typer sub-app pattern (consistent с W5/W6/W8/W9):
- ``ai_eval_app = typer.Typer(help="AI eval framework (Inspect AI nightly suites).")``
- ``app.add_typer(ai_eval_app, name="ai-eval")`` в manage.py
- Команды регистрируются через ``@ai_eval_app.command("name")``
"""

from __future__ import annotations

from pathlib import Path

import typer

ai_eval_app = typer.Typer(help="AI eval framework (Inspect AI nightly suites).")


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
    typer.echo(
        typer.style(f"Total samples: {summary.total_samples}", fg=typer.colors.CYAN)
    )
    if summary.failed:
        typer.echo(typer.style(f"Failed: {summary.failed}", fg=typer.colors.RED))
        raise typer.Exit(code=1)
    typer.echo(typer.style("OK", fg=typer.colors.GREEN))


@ai_eval_app.command("suite")
def ai_eval_suite(
    suite_name: str = typer.Argument(
        ..., help="Имя suite (knowledge_qa, safety_classifier, ...)."
    ),
    artifacts_dir: Path = typer.Option(
        Path("artifacts/inspect-ai"), "--artifacts-dir", help="Каталог для отчётов."
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


__all__ = ("ai_eval_app",)
