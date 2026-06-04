"""Streamlit pages collision validator (Sprint 9 K5 W1).

Цель: автоматическая проверка отсутствия коллизий двузначных префиксов
в каталоге ``src/frontend/streamlit_app/pages/``.

Streamlit использует префикс ``NN_*.py`` для упорядочения страниц в сайдбаре.
Если два файла начинаются с одного и того же ``NN``, Streamlit рандомно
выбирает один из них и пользователь получает «исчезающую страницу».

Запуск:

.. code-block:: bash

    python tools/checks/streamlit_pages.py
    # exit code 0 — нет коллизий
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
        print(f"BAD FILENAMES (must match NN_Name.py): {bad_names}")

    if not collisions and not bad_names:
        print(f"OK: {len(by_prefix)} pages, 0 collisions in {pages_dir}")
    return len(collisions) + len(bad_names)


def main() -> int:
    """Entry point: 0 → success, 1 → collisions found."""
    return 1 if check_collisions(PAGES_ROOT) else 0


if __name__ == "__main__":
    sys.exit(main())
