"""Auto-remove mypy unused-ignore comments.

Usage:
    python tools/fix_mypy_unused_ignores.py [paths...]

Defaults to src/backend/core src/backend/dsl if no paths given.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def main(paths: list[str]) -> int:
    cmd = [sys.executable, "-m", "mypy", "--cache-dir=/dev/null", *paths]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    unused_re = re.compile(
        r"^(?P<path>.+?):(?P<line>\d+):\s*(?:\d+:\s*)?error:\s*"
        r'Unused "type: ignore(?:\[(?P<code>[^\]]+)\])?" comment'
    )

    fixes: dict[str, dict[int, list[str | None]]] = {}
    for line in proc.stdout.splitlines():
        m = unused_re.match(line)
        if not m:
            continue
        path = m.group("path")
        lineno = int(m.group("line"))
        code = m.group("code")
        if code is None:
            fixes.setdefault(path, {}).setdefault(lineno, []).append(None)
        else:
            for c in code.split(","):
                fixes.setdefault(path, {}).setdefault(lineno, []).append(c.strip())

    if not fixes:
        print("No unused-ignore comments found.")
        return 0

    total = 0
    for path, line_codes in fixes.items():
        p = Path(path)
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        for lineno, codes in sorted(line_codes.items(), reverse=True):
            idx = lineno - 1
            if idx >= len(lines):
                continue
            original = lines[idx]
            new_line = original
            for code in codes:
                if code is None:
                    # mypy says the whole ignore comment is unused — remove any form
                    new_line = re.sub(r"#\s*type: ignore(?:\[[^\]]*\])?", "", new_line)
                else:
                    # Remove exact code from ignore list
                    pattern = r"# type: ignore\[([^\]]*)\]"

                    def repl(m: re.Match) -> str:
                        parts = [c.strip() for c in m.group(1).split(",")]
                        filtered = [c for c in parts if c != code]
                        if filtered:
                            return f"# type: ignore[{', '.join(filtered)}]"
                        return ""

                    new_line = re.sub(pattern, repl, new_line)
            # Clean up trailing whitespace / empty comments
            new_line = re.sub(r"\s*#\s*$", "", new_line)
            # Preserve line ending
            if not new_line.endswith("\n") and original.endswith("\n"):
                new_line += "\n"
            lines[idx] = new_line
            total += len(codes)
        p.write_text("".join(lines), encoding="utf-8")

    print(f"Removed {total} unused-ignore directives across {len(fixes)} files.")
    return 0


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        paths = ["src/backend/core", "src/backend/dsl"]
    sys.exit(main(paths))
