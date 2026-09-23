#!/usr/bin/env python3
"""Генератор индекса ADR (Sprint 42 W3).

Сканирует ``docs/adr/*.md``, парсит номер ADR, название и статус,
и записывает сводку в ``docs/adr/INDEX.md``. Может использоваться
локально (``make adr-index``) или в CI (``.github/workflows/adr-sync.yml``).

MINIMAX W6 P1-8 Phase 7 (cycle 153): мигрирован с ``argparse`` на ``typer`` +
``rich`` (libraries > custom, per ADR-0084). Сохранены: typer-native entry +
legacy ``main()`` callback для backward-compat с pre-existing scripts.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "adr"
INDEX_PATH = ADR_DIR / "INDEX.md"

# Парсим заголовок вида "# ADR-0108 — DI DSL для RouteBuilder / call_function / process_fn"
TITLE_RE = re.compile(r"^#\s*(ADR-\d+)\s*[-–—]\s*(.+)$", re.MULTILINE)
# Парсим статус: "* Статус: Accepted (Sprint 40 W1–W5, 2026-06-09)"
STATUS_RE = re.compile(r"^\*\s*Статус:\s*([^\n(]+)", re.MULTILINE)


def _parse_adr(path: Path) -> dict[str, str] | None:
    """Извлекает метаданные из одного ADR-файла."""
    text = path.read_text(encoding="utf-8")
    title_match = TITLE_RE.search(text)
    status_match = STATUS_RE.search(text)
    if not title_match:
        return None
    return {
        "id": title_match.group(1),
        "title": title_match.group(2).strip(),
        "status": (status_match.group(1).strip() if status_match else "Unknown"),
        "file": path.name,
    }


def generate_index() -> str:
    """Возвращает markdown-содержимое INDEX.md."""
    adrs: list[dict[str, str]] = []
    for path in sorted(ADR_DIR.glob("*.md")):
        if path.name == "INDEX.md":
            continue
        parsed = _parse_adr(path)
        if parsed:
            adrs.append(parsed)

    lines = [
        "# ADR Index",
        "",
        "> Автоматически сгенерирован из ``docs/adr/*.md``.",
        "> Последнее обновление: see git log.",
        "",
        "| ADR | Title | Status |",
        "|-----|-------|--------|",
    ]
    for adr in adrs:
        link = f"[{adr['id']}]({adr['file']})"
        title_escaped = adr["title"].replace("|", "\\|")
        lines.append(f"| {link} | {title_escaped} | {adr['status']} |")

    lines.extend(["", f"**Total:** {len(adrs)} ADRs.", ""])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI (backward-compat shim для существующих скриптов).

    Запускает typer app через typer.testing.CliRunner (для тестов)
    или sys.argv (для CLI invocation). Возвращает exit code.
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
    name="generate-adr-index",
    help="Generate docs/adr/INDEX.md from docs/adr/*.md.",
    add_completion=False,
)
_console = Console()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    check: bool = typer.Option(
        False,
        "--check",
        help="Fail if INDEX.md is out of date (CI gate).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print result to stdout instead of writing file.",
    ),
) -> None:
    """Generate docs/adr/INDEX.md."""
    if ctx.invoked_subcommand is not None:
        return

    new_content = generate_index()

    if dry_run:
        # raw stdout write для CI grep-ability
        import sys

        sys.stdout.write(new_content)
        return

    if check:
        if not INDEX_PATH.exists():
            _console.print(f"[red]ADR INDEX missing: {INDEX_PATH}[/]")
            raise typer.Exit(code=1)
        current = INDEX_PATH.read_text(encoding="utf-8")
        if current != new_content:
            _console.print(
                "[red]ADR INDEX is out of date. "
                "Run: uv run python tools/generate_adr_index.py[/]"
            )
            raise typer.Exit(code=1)
        _console.print("[green]ADR INDEX is up to date.[/]")
        return

    INDEX_PATH.write_text(new_content, encoding="utf-8")
    _console.print(
        f"[green]Updated {INDEX_PATH} ({len(new_content)} chars)[/]"
    )


if __name__ == "__main__":
    raise SystemExit(main())
