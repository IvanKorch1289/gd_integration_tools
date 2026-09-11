"""Vale docs linting CI gate — обнаружение accessibility issues в Markdown.

Назначение:
    Sprint 24+ gate #12 (pre-prod-check). Запускает ``vale`` на
    ``docs/docs/`` (где настроен ``.vale.ini`` с Accessibility style).

    Vale проверяет:
    - sanity check/test
    - dummy value/data
    - master branch
    - whitelist/blacklist

    Если ``--fail-on-errors`` и есть errors → exit 1.
    По умолчанию — warn-only (errors не валят build).

Использование:
    python tools/checks/check_vale.py
    python tools/checks/check_vale.py --fail-on-errors
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs" / "docs"


def _check_vale_available() -> str | None:
    """Returns path to vale binary or None."""
    return shutil.which("vale")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Vale docs linting gate")
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=DOCS_DIR,
        help="Path to docs/ для проверки (default: docs/docs/)",
    )
    parser.add_argument(
        "--fail-on-errors",
        action="store_true",
        help="exit 1 если есть errors (по default warn-only)",
    )
    args = parser.parse_args()

    vale_bin = _check_vale_available()
    if vale_bin is None:
        print("[SKIP] vale не установлен — vale check пропущен")
        return 0

    if not args.docs_dir.exists():
        print(f"[ERROR] docs dir '{args.docs_dir}' не существует", file=sys.stderr)
        return 1

    print(f"[INFO] Running vale на {args.docs_dir}")
    # cd в docs dir чтобы найти .vale.ini
    result = subprocess.run(  # noqa: S603
        [vale_bin, "--no-exit", str(args.docs_dir)],
        cwd=str(args.docs_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    stdout = result.stdout
    stderr = result.stderr

    # Парсим output: "✔ 0 errors, 0 warnings and 0 suggestions in N files."
    # Или "✘ N errors, M warnings and K suggestions in N files."
    import re

    error_count = 0
    warning_count = 0
    suggestion_count = 0

    for line in stdout.splitlines():
        m = re.search(r"(\d+)\s+errors?,\s+(\d+)\s+warnings?\s+and\s+(\d+)\s+suggestions?", line)
        if m:
            error_count = int(m.group(1))
            warning_count = int(m.group(2))
            suggestion_count = int(m.group(3))
            break

    print(
        f"[INFO] Vale: errors={error_count}, warnings={warning_count}, "
        f"suggestions={suggestion_count}"
    )

    if result.returncode != 0 and not stdout and stderr:
        # vale вернул ошибку (например, не найден style).
        print(f"[FAIL] vale exited {result.returncode}: {stderr[:500]}", file=sys.stderr)
        return 1

    if args.fail_on_errors and error_count > 0:
        print(f"[FAIL] {error_count} vale errors")
        return 1

    print(
        f"[OK] vale gate passed "
        f"(errors={error_count}, warnings={warning_count})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
