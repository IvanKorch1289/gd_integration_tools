#!/usr/bin/env python3
"""Mass-fix Python 2-style 'except A, B:' → 'except (A, B):'."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Match lines like:
#     except TypeError, ValueError:
#     except ImportError, ValueError, Exception:
# But NOT:
#     except TypeError as exc:
#     except (TypeError, ValueError):
PATTERN = re.compile(
    r"^(\s*)except\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)+)\s*(:)\s*(#.*)?$"
)


def fix_file(path: Path) -> tuple[int, list[str]]:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    changed = 0
    report: list[str] = []
    new_lines: list[str] = []
    for lineno, line in enumerate(lines, 1):
        match = PATTERN.match(line.rstrip("\n").rstrip("\r"))
        if match:
            indent, exc_list, colon, comment = match.groups()
            # Normalize spaces around commas inside the exception list
            exceptions = [e.strip() for e in exc_list.split(",")]
            tail = f" {comment}" if comment else ""
            new_line = f"{indent}except ({', '.join(exceptions)}):{tail}\n"
            new_lines.append(new_line)
            changed += 1
            report.append(f"{path}:{lineno}: {line.rstrip()} -> {new_line.rstrip()}")
        else:
            new_lines.append(line)
    if changed:
        path.write_text("".join(new_lines), encoding="utf-8")
    return changed, report


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src")
    total = 0
    all_reports: list[str] = []
    for path in sorted(root.rglob("*.py")):
        changed, report = fix_file(path)
        if changed:
            total += changed
            all_reports.extend(report)
    for r in all_reports:
        print(r)
    print(f"\nTotal files touched: {len({r.split(':')[0] for r in all_reports})}")
    print(f"Total fixes: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
