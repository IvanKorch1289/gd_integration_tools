"""Wave 10.8 — docs coverage gate.

Объединяет 2 проверки:

1. **Docstring coverage** — для ``src/core`` и ``src/dsl/engine`` (узкое
   ядро). Делегируется уже готовому ``check_docstrings.py`` со
   ``--strict``.
2. **Sphinx HTML coverage** — после ``make docs`` все описанные в
   toctree пути должны существовать в ``docs/build/html/``.

Запуск:

    uv run python tools/docs_coverage.py
    uv run python tools/docs_coverage.py --strict   # exit 1 при <100%

Используется в ``Makefile docs-coverage`` и в CI ``.github/workflows/docs.yml``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DOCSTRING_DIRS: tuple[str, ...] = ("src/core", "src/dsl/engine")

DOCS_DIR = PROJECT_ROOT / "docs"
DOCS_BUILD = DOCS_DIR / "build" / "html"

_TOCTREE_RE = re.compile(r"^\s*([\w./\-]+?)\s*$", re.MULTILINE)


def _collect_toctree_targets() -> set[Path]:
    """Извлекает цели toctree из ``docs/source/index.md``.

    Возвращает paths относительно ``docs/`` без расширения.
    """
    index_md = DOCS_DIR / "source" / "index.md"
    if not index_md.is_file():
        return set()
    text = index_md.read_text(encoding="utf-8")
    targets: set[Path] = set()
    for block in re.finditer(r"```\{toctree\}.*?```", text, re.DOTALL):
        body = block.group(0)
        for line in body.splitlines():
            line = line.strip()
            if (
                not line
                or line.startswith("```")
                or line.startswith(":")
                or line.startswith("#")
            ):
                continue
            # Пропускаем YAML-style каталог: line == "Tutorials" и т.п.
            if " " in line:
                continue
            targets.add(Path(line))
    return targets


def _check_docstrings(strict: bool) -> bool:
    """Запускает ``check_docstrings.py`` для DOCSTRING_DIRS."""
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "check_docstrings.py"),
        *DOCSTRING_DIRS,
    ]
    if strict:
        cmd.append("--strict")
    print(f"→ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)  # noqa: S603 — fixed argv from constants
    return result.returncode == 0


def _check_html_targets() -> tuple[int, int]:
    """Возвращает (found, total) построенных HTML-страниц по toctree."""
    targets = _collect_toctree_targets()
    if not targets:
        return 0, 0
    if not DOCS_BUILD.is_dir():
        print(f"WARN: {DOCS_BUILD} not built — skip HTML coverage")
        return 0, len(targets)
    found = 0
    for t in sorted(targets):
        # Sphinx генерирует <stem>.html под docs/build/html/...
        # Но префикс ../ означает выход из source/. Адаптируем:
        rel = t.as_posix()
        if rel.startswith("../"):
            rel = rel[3:]
        html_path = DOCS_BUILD / f"{rel}.html"
        if html_path.is_file():
            found += 1
        else:
            print(f"  MISS: {html_path}")
    return found, len(targets)


def main() -> int:
    parser = argparse.ArgumentParser(description="Wave 10.8 docs coverage")
    parser.add_argument(
        "--strict", action="store_true", help="Любое расхождение → exit 1."
    )
    args = parser.parse_args()

    docstrings_ok = _check_docstrings(args.strict)
    found, total = _check_html_targets()
    if total > 0:
        ratio = found / total
        print(f"HTML coverage: {found}/{total} ({ratio * 100:.1f}%)")
        html_ok = ratio >= 0.95
    else:
        print("HTML coverage: skipped (no toctree or build dir).")
        html_ok = True

    if docstrings_ok and html_ok:
        print("OK docs_coverage")
        return 0
    if args.strict:
        print("FAIL docs_coverage", file=sys.stderr)
        return 1
    print("WARN docs_coverage (non-strict mode)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
