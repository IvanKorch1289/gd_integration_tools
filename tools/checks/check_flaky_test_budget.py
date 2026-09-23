"""Flaky-test budget policy (Sprint 10 — audit 2026-09-22 P2).

Аудит finding #12 (flaky-test budget): в тестах обнаружены явные xfail
с пометкой «pre-existing flaky test». Каждый xfail должен иметь owner,
issue и expiry. Просроченный quarantine ломает CI.

Правила:
1. Каждый ``@pytest.mark.xfail`` должен иметь:
   - ``reason="issue:#<N>"`` или ``reason="<owner>/<ticket>"``
   - ``strict=True`` ИЛИ expiry date в config.
2. Quarantine allowlist в ``tools/checks/flaky_allowlist.toml``:
   - owner (email)
   - issue (JIRA/GitHub URL)
   - expires (ISO 8601 date)
3. ``--strict`` режим: exit 1 если есть xfail без allowlist entry
   ИЛИ allowlist entry просрочен.

Использование::

    python tools/checks/check_flaky_test_budget.py              # human-readable
    python tools/checks/check_flaky_test_budget.py --strict    # exit 1 if issues
    python tools/checks/check_flaky_test_budget.py --json      # machine output
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"
ALLOWLIST = REPO_ROOT / "tools" / "checks" / "flaky_allowlist.toml"


def _parse_xfail_tests() -> list[dict[str, object]]:
    """Find all @pytest.mark.xfail decorators в tests/.

    Returns list of dicts: file, line, reason, has_owner.
    """
    findings: list[dict[str, object]] = []
    if not TESTS_ROOT.exists():
        return findings
    for py in TESTS_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            for decorator in node.decorator_list:
                src = ast.unparse(decorator)
                if "pytest.mark.xfail" not in src and "xfail" not in src:
                    continue
                # Extract reason.
                reason_match = re.search(r'reason\s*=\s*["\']([^"\']*)["\']', src)
                reason = reason_match.group(1) if reason_match else "<no-reason>"
                line_no = getattr(decorator, "lineno", 0)
                # Heuristic: detect owner format in reason.
                has_owner = bool(re.search(r"(issue:|#[0-9]+|@[\w.-]+)", reason))
                findings.append(
                    {
                        "file": str(py.relative_to(REPO_ROOT)),
                        "line": line_no,
                        "test_name": node.name,
                        "reason": reason,
                        "has_owner": has_owner,
                    }
                )
    return findings


def _parse_allowlist() -> dict[str, dict[str, str]]:
    """Parse flak_allowlist.toml.

    Returns dict keyed by ``file:line:test_name`` → metadata dict.
    """
    if not ALLOWLIST.exists():
        return {}
    try:
        # Minimal TOML parser (project uses tomllib but keep optional).
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError:
            return {}

    with ALLOWLIST.open("rb") as f:
        data = tomllib.load(f)
    return data.get("entries", {})


def _entry_key(file: str, line: int, test_name: str) -> str:
    """Stable key для allowlist matching."""
    return f"{file}:{line}:{test_name}"


def _is_expired(expires: str) -> bool:
    """True если expires date уже прошла."""
    try:
        exp = datetime.fromisoformat(expires)
        if exp.tzinfo is None:
            # Naive datetime — assume UTC.
            exp = exp.replace(tzinfo=UTC)
        return exp < datetime.now(UTC)
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flaky-test budget enforcement")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if issues")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--max-xfail-ratio",
        type=float,
        default=0.05,
        help="Max ratio of xfail tests to total. Default: 0.05.",
    )
    args = parser.parse_args(argv)

    notes: list[str] = []
    issues: list[str] = []

    findings = _parse_xfail_tests()
    n_xfail = len(findings)
    notes.append(f"xfail tests found: {n_xfail}")

    # Count total tests for ratio.
    n_total = 0
    for py in TESTS_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        n_total += content.count("def test_") + content.count("async def test_")
    notes.append(f"Total test functions: ~{n_total}")
    if n_total > 0:
        ratio = n_xfail / n_total
        notes.append(f"xfail ratio: {ratio:.2%}")
        if ratio > args.max_xfail_ratio:
            issues.append(
                f"xfail ratio {ratio:.2%} exceeds threshold "
                f"{args.max_xfail_ratio:.2%} — budget exceeded."
            )

    # Check each xfail against allowlist.
    allowlist = _parse_allowlist()
    notes.append(f"Allowlist entries: {len(allowlist)}")
    unlisted: list[dict[str, object]] = []
    expired: list[dict[str, object]] = []
    for f in findings:
        key = _entry_key(f["file"], int(f["line"]), f["test_name"])  # type: ignore[arg-type]
        entry = allowlist.get(key)
        if entry is None:
            unlisted.append(f)
            continue
        expires = entry.get("expires", "")
        if expires and _is_expired(expires):
            expired.append({"file": f["file"], "key": key, "expires": expires})

    notes.append(f"xfail without allowlist: {len(unlisted)}")
    notes.append(f"Allowlist entries expired: {len(expired)}")

    if unlisted:
        for u in unlisted[:10]:
            issues.append(
                f"xfail without allowlist: {u['file']}:{u['line']} ({u['test_name']})"
            )

    if expired:
        for e in expired[:5]:
            issues.append(
                f"Allowlist entry expired: {e['key']} (expires={e['expires']})"
            )

    output = {
        "xfail_count": n_xfail,
        "total_tests_approx": n_total,
        "ratio": n_xfail / max(n_total, 1),
        "allowlist_entries": len(allowlist),
        "unlisted_count": len(unlisted),
        "expired_count": len(expired),
        "unlisted_sample": unlisted[:10],
        "expired_sample": expired[:5],
        "issues": issues,
        "notes": notes,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"{'=' * 60}")
        print("Flaky-Test Budget Policy (Sprint 10 — audit 2026-09-22 P2)")
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
            print("✅ Flaky-test budget OK")
        print()

    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
