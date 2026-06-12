"""S86 W3: scan step_compilers for Temporal sandbox violations.

V2 P0 #2: compile_agent_invoke_step использовал direct I/O в workflow-функции.
W2 AST scan тесты гарантируют sandbox safety в step_compilers.py.
W3 = full scan всех dsl/workflow/compiler файлов.

Usage:
    python tools/s86_sandbox_scan.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Forbidden direct I/O patterns в workflow-sandbox
FORBIDDEN_PATTERNS = [
    r"\.invoke\(",
    r"\.acompletion\(",
    r"\.completion\(",
    r"\.http_post\(",
    r"\.http_get\(",
]

# Files where direct I/O IS allowed (activity handlers, NOT workflow functions)
ALLOWED_FILES = {
    "activity_bridge.py",  # contains _agent_invoke_activity
}

# Workflow-sandbox safe calls
SAFE_CALLS = [
    "workflow.execute_activity",
    "workflow.execute_child_workflow",
    "workflow.start_activity",
    "asyncio.sleep",  # OK, не I/O
]


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Scan file for forbidden patterns. Returns [(lineno, pattern, line_text)]."""
    if path.name in ALLOWED_FILES:
        return []
    violations: list[tuple[int, str, str]] = []
    src = path.read_text()
    for lineno, line in enumerate(src.splitlines(), 1):
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, line):
                # Check if line is workflow.execute_activity (allowed)
                if any(safe in line for safe in SAFE_CALLS):
                    continue
                violations.append((lineno, pattern, line.strip()))
    return violations


def main() -> int:
    compiler_dir = Path("src/backend/dsl/workflow/compiler")
    files = list(compiler_dir.rglob("*.py"))
    total_violations = 0
    for f in files:
        v = scan_file(f)
        if v:
            print(f"\n{f}:")
            for lineno, pattern, line in v:
                print(f"  L{lineno} [{pattern}]: {line[:100]}")
                total_violations += 1
    if total_violations == 0:
        print(f"OK: scanned {len(files)} files, 0 sandbox violations.")
        return 0
    print(f"\nFAIL: {total_violations} sandbox violations found.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
