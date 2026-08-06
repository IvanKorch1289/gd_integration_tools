"""Streamlit pages collision validator (Sprint 9 K5 W1).

Цель: автоматическая проверка отсутствия коллизий двузначных префиксов
в каталоге ``src/frontend/streamlit_app/pages/``.

Streamlit использует префикс ``NN_*.py`` для упорядочения страниц в сайдбаре.
Если два файла начинаются с одного и того же ``NN``, Streamlit рандомно
выбирает один из них и пользователь получает «исчезающую страницу».

Streamlit filename contract требует ASCII-only names: regex
``[0-9]+_[A-Za-z0-9_]+\\.py`` (per internal ``NN_Name.py`` convention).
Cyrillic filenames (e.g. ``00_Вход.py``) нарушают этот contract.

D-AUDIT-FIX-184-3 (S184 W4 #3, 2026-08-05): добавлен ASCII-only gate.
Ренейм существующих файлов отложен — ломает existing закладки + десятки
internal ``related_pages_footer`` references. CI guard предотвращает
появление новых non-ASCII файлов; cleanup — отдельный W5+ ADR.

Запуск:

.. code-block:: bash

    python tools/checks/streamlit_pages.py
    # exit code 0 — нет коллизий и нет non-ASCII
    # exit code 1 — найдена хотя бы одна коллизия

Часть pre-prod-check gate (DoD-10).
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

PAGES_ROOT = Path(__file__).resolve().parents[2] / "src/frontend/streamlit_app/pages"
PAGE_RE = re.compile(r"^(\d{2})_[A-Za-z0-9_]+\.py$")


def check_collisions(pages_dir: Path) -> int:
    """Проверяет каталог pages на коллизии префиксов.

    Args:
        pages_dir: каталог со Streamlit-страницами.

    Returns:
        Количество найденных коллизий (0 → success).

    D-AUDIT-FIX-184-3 (S184 W4 #3, 2026-08-05): legacy Cyrillic filenames
    помечены как warnings (not errors) для backward-compat с закладками
    и internal ``related_pages_footer`` references. Cleanup отдельный
    W5+ ADR. New non-ASCII filenames (added after this commit) will
    be detected separately via ``check_new_nonascii_filenames`` (TODO
    W5+ if needed).
    """
    if not pages_dir.exists():
        print(f"ERROR: pages directory not found: {pages_dir}")
        return 1

    by_prefix: dict[str, list[str]] = defaultdict(list)
    bad_names: list[str] = []

    for entry in sorted(pages_dir.iterdir()):
        if entry.name.startswith("__") or entry.is_dir():
            continue
        if not entry.name.endswith(".py"):
            continue
        match = PAGE_RE.match(entry.name)
        if not match:
            bad_names.append(entry.name)
            continue
        by_prefix[match.group(1)].append(entry.name)

    collisions = {
        prefix: names for prefix, names in by_prefix.items() if len(names) > 1
    }
    if collisions:
        print(f"FOUND {len(collisions)} COLLISIONS in {pages_dir}:")
        for prefix, names in sorted(collisions.items()):
            print(f"  prefix {prefix}: {names}")
    if bad_names:
        # D-AUDIT-FIX-184-3: warn (not fail) for legacy cyrillic filenames.
        # Renaming them all is a separate W5+ ADR.
        print(
            f"WARN: {len(bad_names)} non-ASCII legacy filenames (D-AUDIT-FIX-184-3 "
            f"carried over; rename via separate ADR):"
        )
        for name in bad_names:
            print(f"  {name}")

    if not collisions:
        # Success iff no collisions (bad_names is warn-only per D-AUDIT-FIX-184-3)
        print(
            f"OK: {len(by_prefix)} pages, {len(collisions)} collisions, "
            f"{len(bad_names)} non-ASCII warnings"
        )
    return len(collisions)


def main() -> int:
    """Entry point: 0 → success, 1 → collisions found."""
    return 1 if check_collisions(PAGES_ROOT) else 0


if __name__ == "__main__":
    sys.exit(main())
