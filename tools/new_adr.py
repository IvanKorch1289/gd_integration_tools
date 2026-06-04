"""Генератор нового ADR из шаблона (Wave s19/k5-w4-quick-wins-pack).

Запуск:
    uv run python tools/new_adr.py "Title here"
    uv run python tools/new_adr.py "Title here" --adr-number 80
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "adr"
TEMPLATE = ROOT / "docs" / "templates" / "adr_template.md"


def _next_number() -> int:
    """Find the next available ADR number by scanning existing files."""
    existing = sorted(ADR_DIR.glob("ADR-*.md"))
    if not existing:
        return 1
    max_num = 0
    for f in existing:
        m = re.match(r"ADR-(\d+)-", f.name)
        if m:
            num = int(m.group(1))
            if num > max_num:
                max_num = num
    return max_num + 1


def main(title: str, adr_number: int | None = None) -> int:
    if not TEMPLATE.exists():
        print(f"FAIL: template not found at {TEMPLATE}", file=sys.stderr)
        return 1

    if not ADR_DIR.is_dir():
        print(f"FAIL: ADR dir not found at {ADR_DIR}", file=sys.stderr)
        return 1

    if adr_number is None:
        adr_number = _next_number()

    slug = re.sub(r"[^\w]+", "-", title.lower()).strip("-")
    filename = f"ADR-{adr_number:04d}-{slug}.md"
    out_path = ADR_DIR / filename

    if out_path.exists():
        print(f"FAIL: {out_path} already exists", file=sys.stderr)
        return 1

    template_content = TEMPLATE.read_text(encoding="utf-8")
    today = date.today().isoformat()
    content = template_content.replace("{{title}}", title).replace("{{date}}", today)

    out_path.write_text(content, encoding="utf-8")
    print(f"OK: created {out_path}")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scaffold a new ADR")
    parser.add_argument("title", help="ADR title (e.g., 'My new feature')")
    parser.add_argument(
        "--adr-number",
        type=int,
        default=None,
        help="ADR number (default: auto-increment from existing)",
    )
    args = parser.parse_args()
    sys.exit(main(args.title, args.adr_number))
