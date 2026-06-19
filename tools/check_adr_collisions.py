"""Check для ADR collision-slots (S168 W17 P2-3).

S168 W17 P2-3 (per master prompt v8): "Deduplicate ADRs: 11
collision-slots → завести -v2 суффикс или -a/-b, обновить
обратные ссылки в sprint-closure".

Этот скрипт — check tool для pre-commit / CI. Если в будущем
любой PR создаст 2+ ADR файла на один номер — script fail'ит
с понятным сообщением.

Per Ponytail minimum, текущий commit:
- ADD check script
- Не делает rename существующих collisions (S169+ по плану)
- Per ADR-0243 migration plan

Usage:
    python tools/check_adr_collisions.py [--docs-dir docs/adr]

Exit code:
    0 = OK
    1 = collision found
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ADR slot collisions")
    parser.add_argument(
        "--docs-dir",
        default="docs/adr",
        help="Path to ADR directory (default: docs/adr)",
    )
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.exists():
        print(f"ERROR: ADR directory not found: {docs_dir}", file=sys.stderr)
        return 1

    # Group ADRs by their number (4 digits prefix)
    # Format: 0123-...md → 0123
    by_slot: dict[str, list[Path]] = defaultdict(list)
    for adr_file in sorted(docs_dir.glob("0*.md")):
        match = re.match(r"^(\d{4})-", adr_file.name)
        if not match:
            continue
        slot = match.group(1)
        by_slot[slot].append(adr_file)

    # Find collisions (slots with >1 files)
    collisions = {
        slot: files for slot, files in by_slot.items() if len(files) > 1
    }

    if not collisions:
        print(f"OK: 0 collisions in {docs_dir}")
        return 0

    print(f"FAIL: {len(collisions)} collision slot(s) found:", file=sys.stderr)
    for slot, files in sorted(collisions.items()):
        print(f"  ADR-{slot}:", file=sys.stderr)
        for f in files:
            print(f"    - {f.name}", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Per ADR-0243 plan: rename one of the duplicates to "
        "``<slot>a-...md`` (or ``-v2``) suffix.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
