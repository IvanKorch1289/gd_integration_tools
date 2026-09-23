#!/usr/bin/env python3
"""Cycle-49 (D-AUDIT-3024): silence F401 in multi-line parenthesized imports.

Для каждого multi-line import ``from X import (\n    Y,\n    Z,\n)`` где
имена — re-exports, добавляет ``# noqa: F401 — re-export`` на
первую строку.

Pattern:
    # Before (ruff F401):
    from src.backend.core.di.providers.ai import (
        get_a,
        get_b,
    )

    # After:
    from src.backend.core.di.providers.ai import (  # noqa: F401 — re-export
        get_a,
        get_b,
    )

Usage:
    # Default — DRY-RUN (safe, no file changes):
    python tools/add_f401_multiline_noqa.py --root src/

    # Apply changes (requires explicit --apply):
    python tools/add_f401_multiline_noqa.py --root src/ --apply

MINIMAX W6 P1-8 Phase 9 (cycle 153): мигрирован с ``argparse`` на ``typer`` +
``rich`` (libraries > custom, per ADR-0084). Сохранены: typer-native entry +
legacy ``main()`` callback для backward-compat с pre-existing scripts.

Safety: default — DRY-RUN mode (печатает файлы которые would be changed,
без записи). Требует explicit ``--apply`` для реальных file changes.
Это предотвращает unintended side effects при automated testing.

WARNING: tool имеет known issue — regex matches lines в docstrings (NOT
только real imports). Перед production use добавить AST-based detection
(см. ADR-0332 roadmap Phase 10).
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console

_logger = logging.getLogger(__name__)


def _process_file(path: Path) -> tuple[int, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0, content
    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    changes = 0
    for line in lines:
        stripped = line.rstrip("\n")
        # Detect start of multi-line parenthesized from-import (без закрывающей ")" на этой строке)
        if (
            stripped.lstrip().startswith("from ")
            and " import " in stripped
            and "(" in stripped
            and ")" not in stripped.split("#", 1)[0]  # игнорируем комментарии
            and "# noqa" not in line
        ):
            suffix = "\n" if line.endswith("\n") else ""
            indent = len(stripped) - len(stripped.lstrip())
            prefix = stripped[:indent]
            # Find position to insert comment: after ``import (``
            import_idx = stripped.find(" import (")
            if import_idx == -1:
                new_lines.append(line)
                continue
            insert_pos = import_idx + len(" import (") - 1  # position of (
            # Build new line: ``from X import (  # noqa: F401 — re-export\n``
            new_stripped = (
                stripped[: insert_pos + 1]
                + "  # noqa: F401 — re-export"
                + stripped[insert_pos + 1 :]
            )
            new_lines.append(new_stripped + suffix)
            changes += 1
        else:
            new_lines.append(line)
    if changes == 0:
        return 0, content
    return changes, "".join(new_lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI (backward-compat shim для существующих скриптов).

    Запускает typer app через typer.testing.CliRunner (для тестов)
    или sys.argv (для CLI invocation). Возвращает exit code.

    Default — DRY-RUN mode (только print changed files, без записи).
    Требует explicit ``--apply`` для реальных file changes.
    """
    if argv is not None:
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    # CLI invocation: typer сам подхватит sys.argv[1:]
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


app = typer.Typer(
    name="add-f401-multiline-noqa",
    help="Silence F401 in multi-line parenthesized imports (D-AUDIT-3024 cycle-49).",
    add_completion=False,
)
_console = Console()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    root: str = typer.Option(
        "src/backend",
        "--root",
        help="Root dir to walk.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Enable DEBUG logging.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply changes (default: DRY-RUN, only print summary).",
    ),
) -> None:
    """Silence F401 in multi-line parenthesized imports."""
    if ctx.invoked_subcommand is not None:
        return

    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)

    root_path = Path(root)
    files = list(root_path.rglob("*.py"))
    total_changes = 0
    changed_files: list[tuple[Path, int]] = []
    for f in files:
        if "__pycache__" in f.parts:
            continue
        changes, new_content = _process_file(f)
        if changes > 0:
            changed_files.append((f, changes))
            total_changes += changes
            if apply:
                f.write_text(new_content, encoding="utf-8")
                _console.print(f"  [green]Updated[/] {f} (+{changes})")
            else:
                _console.print(f"  [yellow]Would update[/] {f} (+{changes})")

    mode = "[green]applied[/]" if apply else "[yellow]DRY-RUN[/]"
    _console.print(
        f"\n[bold]Mode: {mode}, Total changes: {total_changes}, "
        f"Files affected: {len(changed_files)}[/]"
    )


if __name__ == "__main__":
    raise SystemExit(main())
