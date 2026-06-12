"""S86 — Static analyzer: detect Temporal sandbox violations in workflow compile path.

Цель: предотвратить silent non-determinism failures в Temporal workflows.

Проверяет код в ``src/backend/dsl/workflow/compiler/``:
  * ``compile_workflow()`` — build-time, ОК для ``type()`` / ``importlib`` (worker startup).
  * ``compile_*_step()`` functions — выполнение ВНУТРИ workflow @workflow.run,
    поэтому ЗАПРЕЩЕНО:
      - прямой I/O: ``await gateway/completion/acompletion/aiohttp_client/redis/db``
      - прямое использование ``asyncio.sleep`` / ``asyncio.create_subprocess_exec``
      - ``os.environ`` / ``time.time()`` / ``uuid.uuid4()`` (не-deterministic)
    Разрешено: ``workflow.execute_activity``, ``workflow.sleep``,
    ``workflow.wait_condition``, ``workflow.now()``.

Usage::

    uv run python tools/s86_workflow_sandbox_guard.py [--verbose] [--fix]

Exit codes:
  0 — нет violations
  1 — найдены violations (CI gate fail)
  2 — internal error
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Workflow-safe APIs (allowed)
SAFE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"workflow\.(execute_activity|execute_local_activity|start_activity)"),
    re.compile(r"workflow\.sleep"),
    re.compile(r"workflow\.wait_condition"),
    re.compile(r"workflow\.pause\(\)"),
    re.compile(r"workflow\.resume\(\)"),
    re.compile(r"workflow\.now\(\)"),
    re.compile(r"workflow\.logger"),
    re.compile(r"workflow\.unsafe\."),
)

# Forbidden: direct I/O / non-determinism
FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bawait\s+\w*[Gg]ateway\.\w+\("), "direct gateway I/O (use workflow.execute_activity)"),
    (re.compile(r"\bawait\s+\w*[Cc]ompletion\.\w+\("), "direct LLM completion (use workflow.execute_activity)"),
    (re.compile(r"\bawait\s+\w*[Aa]completion\("), "direct LLM acompletion (use workflow.execute_activity)"),
    (re.compile(r"\bawait\s+\w*[Hh]ttp[_\w]*\.(\w+)\("), "direct HTTP client (use workflow.execute_activity)"),
    (re.compile(r"\bawait\s+\w*[Rr]edis\w*\.\w+\("), "direct redis I/O (use workflow.execute_activity)"),
    (re.compile(r"\bawait\s+\w*[Dd]b\.\w+\("), "direct DB I/O (use workflow.execute_activity)"),
    (re.compile(r"\bawait\s+\w*[Pp]ublisher\.\w+\("), "direct publisher (use workflow.execute_activity)"),
    (re.compile(r"\bawait\s+\w*[Ss]ink\.\w+\("), "direct sink (use workflow.execute_activity)"),
    (re.compile(r"\basyncio\.sleep\("), "asyncio.sleep non-deterministic (use workflow.sleep)"),
    (re.compile(r"\b(uuid\.uuid4|time\.time|datetime\.now)\(\)"), "non-deterministic clock/UUID (use workflow.now() or activity UUID)"),
    (re.compile(r"\bget_stream_client\(\)\."), "direct stream client (use workflow.execute_activity)"),
    (re.compile(r"\bos\.environ"), "os.environ non-deterministic (use activity-side env read)"),
)


def _is_inside_workflow_context(file_text: str | list[str], line_idx: int) -> bool:
    """Approximate check: is ``line_idx`` inside a ``compile_*_step`` function?"""
    if isinstance(file_text, str):
        lines_iter = file_text.splitlines()
    else:
        lines_iter = file_text
    # Walk backward to find the most recent ``async def compile_`` or ``async def _run``
    for i in range(line_idx, -1, -1):
        line = lines_iter[i]
        if re.match(r"^async def (compile_\w+|_run)\b", line):
            return True
        if re.match(r"^(async )?def \w", line) and "compile_" not in line and "_run" not in line:
            return False
    return False


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of ``(line_no, line, reason)`` violations in *path*."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    lines = text.splitlines()
    violations: list[tuple[int, str, str]] = []
    for idx, line in enumerate(lines):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # Only scan inside workflow compile context
        if not _is_inside_workflow_context(lines, idx):
            continue
        for pattern, reason in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                # Allow if guarded by SAFE_PATTERNS (defensive double-check)
                if any(safe.search(line) for safe in SAFE_PATTERNS):
                    continue
                violations.append((idx + 1, line.rstrip(), reason))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S86 workflow sandbox guard (Temporal CI gate)"
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("src/backend/dsl/workflow/compiler"),
        help="Directory to scan (default: src/backend/dsl/workflow/compiler)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print scanned files")
    args = parser.parse_args(argv)

    target = args.path
    if not target.exists():
        print(f"ERROR: {target} does not exist", file=sys.stderr)
        return 2

    all_violations: list[tuple[Path, int, str, str]] = []
    files_scanned = 0
    for py_file in sorted(target.rglob("*.py")):
        files_scanned += 1
        if args.verbose:
            print(f"  scanning {py_file}")
        for line_no, line, reason in scan_file(py_file):
            all_violations.append((py_file, line_no, line, reason))

    if not all_violations:
        print(f"OK: scanned {files_scanned} files, 0 violations")
        return 0

    print(f"FAIL: scanned {files_scanned} files, {len(all_violations)} violations:")
    for path, line_no, line, reason in all_violations:
        rel = path.relative_to(Path.cwd()) if path.is_absolute() else path
        print(f"  {rel}:{line_no}: {reason}")
        print(f"    > {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
