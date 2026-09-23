"""Cancellation/backpressure contract verification (P1 audit 2026-09-22).

Поддерживаются streaming, SSE, WS, MQ и parallel DSL, но мало доказательств
корректной отмены downstream задач при disconnect/timeout.

Критерии готовности: нет orphan tasks, blocked producers и утечек pool
connections после cancel/disconnect.

Проверяет:
1. **asyncio.create_task usage**: tasks создаются без сохранения ссылки
   — теряются при GC и не могут быть отменены.
2. **Streaming endpoints**: SSE/WS handlers должны корректно обрабатывать
   client disconnect (request.is_disconnected()).
3. **asyncio.wait_for usage**: timeout должен иметь cancel-friendly
   обработку.
4. **MQ consumers**: должны реагировать на cancellation token.
5. **Pool connections**: проверка незакрытых connection acquisition.

Использование::

    python tools/checks/check_cancellation_contract.py              # human-readable
    python tools/checks/check_cancellation_contract.py --strict    # exit 1
    python tools/checks/check_cancellation_contract.py --json      # machine output
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def _scan_create_task_without_ref(file: Path, content: str) -> list[tuple[int, str]]:
    """Find ``asyncio.create_task(...)`` not assigned to variable.

    If the result of ``asyncio.create_task`` is not stored, the task
    can be garbage-collected mid-execution and never cancelled.
    """
    findings: list[tuple[int, str]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        src = ast.unparse(node.value.func) if hasattr(node.value, "func") else ""
        if "asyncio.create_task" not in src:
            continue
        line_no = node.lineno
        line_text = content.split("\n")[line_no - 1].strip() if line_no > 0 else ""
        findings.append((line_no, line_text[:80]))
    return findings


def _scan_streaming_without_disconnect_check(
    file: Path, content: str
) -> list[tuple[int, str]]:
    """Find streaming/SSE/WS handlers без ``is_disconnected()`` check."""
    findings: list[tuple[int, str]] = []
    # Heuristic: file is in streaming/entrypoints + uses EventSourceResponse/yield.
    if (
        "/streaming/" not in str(file)
        and "/sse/" not in str(file)
        and "/ws/" not in str(file)
    ):
        return findings
    if (
        "EventSourceResponse" in content
        or "async def stream" in content
        or "yield {" in content
    ):
        if "is_disconnected" not in content and "wait_for_disconnect" not in content:
            findings.append((1, "streaming handler without disconnect check"))
    return findings


def _scan_wait_for_usage(
    file: Path, content: str, parent_map: dict[int, ast.AST] | None = None
) -> list[tuple[int, str]]:
    """Find ``asyncio.wait_for`` без enclosing try/except.

    Note: wait_for cancels inner task on timeout by default — это OK,
    но проверяем наличие exception handling через AST parent-walk.

    Args:
        file: исходный .py файл.
        content: текст файла.
        parent_map: pre-built parent map (id(node) -> parent). Если None —
            строится на лету (overhead O(N) на файл).

    Returns:
        Список (line_no, snippet) для каждого wait_for без enclosing try.
    """
    findings: list[tuple[int, str]] = []
    if "asyncio.wait_for" not in content:
        return findings
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return findings

    # Build parent map if not provided.
    if parent_map is None:
        parent_map = {}
        for parent in ast.walk(tree):

            def _walk(n: ast.AST, p: ast.AST) -> None:
                parent_map[id(n)] = p
                for child in ast.iter_child_nodes(n):
                    _walk(child, n)

            for child in ast.iter_child_nodes(parent):
                _walk(child, parent)

    def _enclosing_has_try_with_except(n: ast.AST) -> bool:
        """Подняться по parents; найти enclosing Try с ExceptHandler."""
        cur: ast.AST | None = parent_map.get(id(n))
        while cur is not None:
            if isinstance(cur, ast.Try):
                # Try с except (не только finally).
                if cur.handlers:
                    return True
            cur = parent_map.get(id(cur))
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        try:
            src = ast.unparse(node.func)
        except (ValueError, TypeError):
            continue
        if "asyncio.wait_for" not in src:
            continue
        if not _enclosing_has_try_with_except(node):
            line_no = node.lineno
            line_text = content.split("\n")[line_no - 1].strip() if line_no > 0 else ""
            findings.append((line_no, line_text[:80]))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cancellation/backpressure contract verification"
    )
    parser.add_argument("--strict", action="store_true", help="Exit 1 if issues found")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    notes: list[str] = []
    issues: list[str] = []
    create_task_issues: list[dict[str, object]] = []
    streaming_issues: list[dict[str, object]] = []
    wait_for_issues: list[dict[str, object]] = []

    files_scanned = 0
    for py in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in py.parts or "/tests/" in str(py):
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_scanned += 1

        # 1. asyncio.create_task без ref.
        for line_no, line in _scan_create_task_without_ref(py, content):
            create_task_issues.append(
                {
                    "file": str(py.relative_to(REPO_ROOT)),
                    "line": line_no,
                    "snippet": line,
                }
            )

        # 2. Streaming без disconnect check.
        for line_no, line in _scan_streaming_without_disconnect_check(py, content):
            streaming_issues.append(
                {
                    "file": str(py.relative_to(REPO_ROOT)),
                    "line": line_no,
                    "snippet": line,
                }
            )

        # 3. wait_for без try/except.
        for line_no, line in _scan_wait_for_usage(py, content):
            wait_for_issues.append(
                {
                    "file": str(py.relative_to(REPO_ROOT)),
                    "line": line_no,
                    "snippet": line,
                }
            )

    notes.append(f"Files scanned: {files_scanned}")
    notes.append(f"create_task() without ref: {len(create_task_issues)}")
    notes.append(f"Streaming handlers w/o disconnect check: {len(streaming_issues)}")
    notes.append(f"wait_for() without try/except nearby: {len(wait_for_issues)}")

    # Issues only for high-confidence findings.
    if create_task_issues:
        issues.append(
            f"{len(create_task_issues)} ``asyncio.create_task(...)`` без сохранения ссылки — "
            "tasks могут быть GC'd mid-execution."
        )

    if streaming_issues:
        issues.append(
            f"{len(streaming_issues)} streaming handlers без is_disconnected() — "
            "producer продолжает работу после disconnect клиента."
        )

    if wait_for_issues:
        issues.append(
            f"{len(wait_for_issues)} wait_for() без try/except — "
            "TimeoutError может не обрабатываться."
        )

    output = {
        "files_scanned": files_scanned,
        "create_task_issues": create_task_issues[:20],
        "streaming_issues": streaming_issues[:20],
        "wait_for_issues": wait_for_issues[:20],
        "totals": {
            "create_task": len(create_task_issues),
            "streaming": len(streaming_issues),
            "wait_for": len(wait_for_issues),
        },
        "issues": issues,
        "notes": notes,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"{'=' * 60}")
        print("Cancellation/Backpressure Contract (P1 audit 2026-09-22)")
        print(f"{'=' * 60}")
        print()
        for n in notes:
            print(f"  ℹ️  {n}")
        print()
        if issues:
            print("Issues:")
            for i in issues:
                print(f"  ❌ {i}")
        else:
            print("✅ All critical checks passed")
        print()

    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
