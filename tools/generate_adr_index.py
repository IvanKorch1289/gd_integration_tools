#!/usr/bin/env python3
"""Генератор индекса ADR (Sprint 42 W3).

Сканирует ``docs/adr/*.md``, парсит номер ADR, название и статус,
и записывает сводку в ``docs/adr/INDEX.md``. Может использоваться
локально (``make adr-index``) или в CI (``.github/workflows/adr-sync.yml``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

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
    parser = argparse.ArgumentParser(description="Generate docs/adr/INDEX.md")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if INDEX.md is out of date (CI gate).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print result to stdout instead of writing file.",
    )
    args = parser.parse_args(argv)

    new_content = generate_index()

    if args.dry_run:
        sys.stdout.write(new_content)
        return 0

    if args.check:
        if not INDEX_PATH.exists():
            print(f"ADR INDEX missing: {INDEX_PATH}", file=sys.stderr)
            return 1
        current = INDEX_PATH.read_text(encoding="utf-8")
        if current != new_content:
            print(
                "ADR INDEX is out of date. Run: uv run python tools/generate_adr_index.py",
                file=sys.stderr,
            )
            return 1
        print("ADR INDEX is up to date.")
        return 0

    INDEX_PATH.write_text(new_content, encoding="utf-8")
    print(f"Updated {INDEX_PATH} ({len(new_content)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
