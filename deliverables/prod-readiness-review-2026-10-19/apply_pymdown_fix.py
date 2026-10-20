#!/usr/bin/env python3
"""Pymdown-extensions cap fix (G-12 from prod-readiness review).

Single-line change: pyproject.toml:519 has
    "pymdown-extensions>=10.7.0,<11.0.0"
which excludes both fixes for:
  - CVE-2026-61632 (PYSEC-2026-3609): path traversal in pymdownx/b64.py
    (targeted file read, not arbitrary read), fix in 11.0.0
  - CVE-2026-67422 (PYSEC-2026-3654): ReDoS in four inline processors,
    reachable in DEFAULT configuration, fix in 11.0.1

Removes the upper cap, allowing 11.0.0+ (with the fixes). mkdocs-material
itself pins no upper bound, so removing the cap is safe.

Usage:
    python deliverables/prod-readiness-review-2026-10-19/apply_pymdown_fix.py --check
    python deliverables/prod-readiness-review-2026-10-19/apply_pymdown_fix.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"

OLD = '"pymdown-extensions>=10.7.0,<11.0.0"'
NEW = '"pymdown-extensions>=10.7.0"'  # upper cap removed; 11.0.0+ has the CVE fixes


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove pymdown-extensions upper cap")
    parser.add_argument("--check", action="store_true", help="dry-run, no writes")
    args = parser.parse_args()

    if not PYPROJECT.exists():
        print(f"ERROR: {PYPROJECT} not found", file=sys.stderr)
        return 1

    text = PYPROJECT.read_text(encoding="utf-8")
    if OLD not in text:
        print(f"ERROR: old_text not found in {PYPROJECT.name} (drift?)", file=sys.stderr)
        return 1
    if text.count(OLD) > 1:
        print(f"ERROR: old_text matches {text.count(OLD)} times (not unique)", file=sys.stderr)
        return 1

    new_text = text.replace(OLD, NEW, 1)

    print("=" * 60)
    print("Pymdown-extensions cap fix (G-12 from review 2026-10-19)")
    print("=" * 60)
    print(f"File:   {PYPROJECT.relative_to(REPO)}")
    print(f"Line:   519 (docs extra)")
    print(f"Before: {OLD}")
    print(f"After:  {NEW}")
    print(f"Closes: CVE-2026-61632 (PYSEC-2026-3609, path traversal)")
    print(f"        CVE-2026-67422 (PYSEC-2026-3654, ReDoS, default-reachable)")
    print("-" * 60)
    if args.check:
        print("Mode:   dry-run (no writes)")
    else:
        PYPROJECT.write_text(new_text, encoding="utf-8")
        print("Mode:   APPLIED")
    print()
    print("Verification (post-apply):")
    print("  grep 'pymdown-extensions' pyproject.toml  # expect: no '<11.0.0' cap")
    print("  make sbom-diff-gate                      # expect: no PYSEC-2026-3609/3654")
    print("  pip install -e '.[docs]'                 # expect: pymdown-extensions 11.0.1+")
    return 0


if __name__ == "__main__":
    sys.exit(main())
