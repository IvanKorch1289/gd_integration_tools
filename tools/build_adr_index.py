"""Генератор ``docs/adr/INDEX.md`` (Wave 10.6).

Сканирует ``docs/adr/*.md`` и извлекает номер ADR из имени файла.
Поддерживает два паттерна именования:

1. **Текущий** (v22+): ``0050-net-waf-strict-single-entry.md``
   (только номер + slug, без префикса ``ADR-``).
2. **Legacy** (Wave 10.6): ``ADR-0050-net-waf-strict-single-entry.md``
   (с префиксом ``ADR-``).

Извлекает заголовок (первая ``# ...`` строка) и status (если присутствует
``Status: ...``, ``- **Status**:`` или ``**Status**:``). Сортирует по
номеру + slug; повторяющиеся номера допускаются.

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

# Поддержка обоих паттернов: legacy (ADR-XXXX-name.md) и current (XXXX-name.md).
_NUM_RE_LEGACY = re.compile(r"^ADR-(\d{3,4})-(.+)\.md$")
_NUM_RE_CURRENT = re.compile(r"^(\d{3,4})-(.+)\.md$")
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_STATUS_PATTERNS = (
    # English patterns
    re.compile(r"^Status:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^-\s*\*\*Status\*\*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\*\*Status\*\*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    # Russian patterns (primary — текущий проект использует русский)
    re.compile(r"^Статус:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^-\s*\*\*Статус\*\*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\*\*Статус\*\*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    # Russian с bullet `*` (формат файлов v22+)
    re.compile(r"^\*\s*Статус:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\*\s*\*\*Статус\*\*:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
)


def _parse_filename(name: str) -> tuple[str, str] | None:
    """Парсит имя файла, возвращает (num, slug) или None если не ADR."""
    m = _NUM_RE_LEGACY.match(name)
    if m:
        return m.group(1), m.group(2)
    m = _NUM_RE_CURRENT.match(name)
    if m:
        return m.group(1), m.group(2)
    return None


def _extract_meta(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    title_m = _TITLE_RE.search(text)
    title = title_m.group(1).strip() if title_m else path.stem
    status = "—"
    for pat in _STATUS_PATTERNS:
        m = pat.search(text)
        if m:
            # Strip markdown bold (**) и ограничиваем до 60 chars
            raw = m.group(1).strip()
            raw = raw.replace("**", "").replace("__", "")
            status = raw[:60]
            break
    return title, status


def main() -> int:
    if not ADR_DIR.is_dir():
        print(f"FAIL: {ADR_DIR} not found", file=sys.stderr)
        return 1

    rows: list[tuple[str, str, str, str]] = []
    for adr_file in sorted(ADR_DIR.glob("*.md")):
        # Пропускаем INDEX.md (этот файл — выход скрипта)
        if adr_file.name == "INDEX.md":
            continue
        parsed = _parse_filename(adr_file.name)
        if parsed is None:
            continue
        num, slug = parsed
        title, status = _extract_meta(adr_file)
        rows.append((num, slug, title, status))

    if not rows:
        print("FAIL: no ADR files matched", file=sys.stderr)
        return 1

    # Группируем по номеру для явной диагностики collision-слотов.
    by_num: dict[str, list[tuple[str, str, str, str]]] = {}
    for r in rows:
        by_num.setdefault(r[0], []).append(r)
    collisions = sorted(n for n, vs in by_num.items() if len(vs) > 1)
    unique_slots = sorted(by_num.keys())

    lines: list[str] = [
        "# Architecture Decision Records (ADR) — индекс",
        "",
        f"Всего ADR-файлов: **{len(rows)}**; уникальных слотов: **{len(unique_slots)}**.",
    ]
    if collisions:
        lines += [
            "",
            f"⚠️ Collision-слоты ({len(collisions)}): "
            + ", ".join(f"ADR-{n}" for n in collisions)
            + ". Каждая пара — два ADR на один номер; ренейм отложен из-за внешних ссылок (см. R3.0).",
        ]
    lines += [
        "",
        "| № | Заголовок | Статус | Файл |",
        "|---|-----------|--------|------|",
    ]
    for num, slug, title, status in rows:
        # Используем РЕАЛЬНОЕ имя файла (без префикса ADR-), а не реконструированное.
        # Так links работают для обоих паттернов.
        # Находим исходный файл по num+slug:
        actual_filename = None
        for f in ADR_DIR.glob("*.md"):
            if f.name == "INDEX.md":
                continue
            p = _parse_filename(f.name)
            if p and p[0] == num and p[1] == slug:
                actual_filename = f.name
                break
        filename = actual_filename or f"{num}-{slug}.md"
        marker = " *(collision)*" if num in collisions else ""
        lines.append(
            f"| {num}{marker} | {title} | {status} | [{filename}]({filename}) |"
        )
    lines.append("")
    lines.append(
        "_Сгенерировано `tools/build_adr_index.py`. "
        "Не редактировать вручную — запустите скрипт повторно._"
    )

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"OK adr_index: {len(rows)} files, {len(unique_slots)} unique slots, "
        f"{len(collisions)} collisions → {OUT}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
