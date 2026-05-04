"""Генератор ``docs/adr/INDEX.md`` (Wave 10.6).

Сканирует ``docs/adr/ADR-*.md``, извлекает заголовок (первая ``# ...``
строка) и status (если присутствует ``Status: ...`` либо ``- **Status**:``).
Сортирует по номеру + slug; повторяющиеся номера допускаются (например
ADR-001-dsl-central-abstraction и ADR-001-layered-architecture).

Запуск:
    uv run python tools/build_adr_index.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "adr"
OUT = ADR_DIR / "INDEX.md"

_NUM_RE = re.compile(r"^ADR-(\d{3})-(.+)\.md$")
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_STATUS_PATTERNS = (
    re.compile(r"^Status:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^-\s*\*\*Status\*\*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\*\*Status\*\*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
)


def _extract_meta(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    title_m = _TITLE_RE.search(text)
    title = title_m.group(1).strip() if title_m else path.stem
    status = "—"
    for pat in _STATUS_PATTERNS:
        m = pat.search(text)
        if m:
            status = m.group(1).strip()[:40]
            break
    return title, status


def main() -> int:
    if not ADR_DIR.is_dir():
        print(f"FAIL: {ADR_DIR} not found", file=sys.stderr)
        return 1

    rows: list[tuple[str, str, str, str]] = []
    for adr_file in sorted(ADR_DIR.glob("ADR-*.md")):
        m = _NUM_RE.match(adr_file.name)
        if not m:
            continue
        num, slug = m.group(1), m.group(2)
        title, status = _extract_meta(adr_file)
        rows.append((num, slug, title, status))

    if not rows:
        print("FAIL: no ADR files matched", file=sys.stderr)
        return 1

    lines: list[str] = [
        "# Architecture Decision Records (ADR) — индекс",
        "",
        f"Всего ADR: **{len(rows)}**.",
        "",
        "| № | Заголовок | Статус | Файл |",
        "|---|-----------|--------|------|",
    ]
    for num, slug, title, status in rows:
        filename = f"ADR-{num}-{slug}.md"
        lines.append(f"| {num} | {title} | {status} | [{filename}]({filename}) |")
    lines.append("")
    lines.append(
        "_Сгенерировано `tools/build_adr_index.py`. "
        "Не редактировать вручную — запустите скрипт повторно._"
    )

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK adr_index: {len(rows)} entries → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
