"""S64 Org-2 — CI guard: detect duplicate script paths between scripts/ and tools/.

Catches the class of bug we hit in S64 Org-1: scripts/check_layers.py
was a divergent copy of tools/check_layers.py. Both diverged for weeks
and only got caught by code review.

This check fails (exit 1) if any file in scripts/ has the same name as
a file in tools/. The fix is to delete the duplicate and reference the
canonical one.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo = Path("/home/user/dev/gd_integration_tools")
    scripts_dir = repo / "scripts"
    tools_dir = repo / "tools"

    if not scripts_dir.exists() or not tools_dir.exists():
        print("scripts/ or tools/ not found — skip")
        return 0

    scripts_files = {
        p.name
        for p in scripts_dir.iterdir()
        if p.is_file() and p.suffix in (".py", ".sh")
    }
    tools_files = {
        p.name
        for p in tools_dir.iterdir()
        if p.is_file() and p.suffix in (".py", ".sh")
    }

    duplicates = sorted(scripts_files & tools_files)

    if not duplicates:
        print("OK: no duplicate scripts between scripts/ and tools/")
        return 0

    print(
        f"FAIL: {len(duplicates)} duplicate(s) between scripts/ and tools/:",
        file=sys.stderr,
    )
    for name in duplicates:
        scripts_path = scripts_dir / name
        tools_path = tools_dir / name
        print(f"  - {name}", file=sys.stderr)
        print(
            f"    scripts/  ({scripts_path.stat().st_size} bytes, mtime {scripts_path.stat().st_mtime:.0f})",
            file=sys.stderr,
        )
        print(
            f"    tools/    ({tools_path.stat().st_size} bytes, mtime {tools_path.stat().st_mtime:.0f})",
            file=sys.stderr,
        )

    print(
        "\nFix: pick the canonical version (likely tools/) and delete the other. Then update any references in Makefile / .pre-commit-config.yaml.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
