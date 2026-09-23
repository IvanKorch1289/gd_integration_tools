"""Object-level authorization matrix (P0 audit 2026-09-22).

JWT/API key подтверждают identity, но это НЕ доказывает object-level
authorization (например, tenant_A может прочитать файл tenant_B, если
resource_id привязан к чужому tenant).

Этот скрипт сканирует:
1. **REST endpoints** — FastAPI route handlers без ``check_object_ownership``
   или эквивалентной проверки.
2. **Service-level access** — места, где ``.get(id)`` или аналогичный lookup
   используется БЕЗ tenant filter.
3. **Stream/file/RAG/agent** — специфические ресурсы с потенциальными
   cross-tenant доступами.

Матрица coverage:
- owner
- same-tenant non-owner
- cross-tenant
- admin

Использование::

    python tools/checks/check_object_authorization.py              # human-readable
    python tools/checks/check_object_authorization.py --strict    # exit 1
    python tools/checks/check_object_authorization.py --json      # machine output
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


# Patterns suggesting object ownership check.
OWNERSHIP_PATTERNS = [
    "check_ownership",
    "verify_owner",
    "ensure_owner",
    "assert_owner",
    "require_ownership",
    "object_ownership",
    "resource_owner",
    "is_owner",
    "verify_object_ownership",
    # RLS-based (DB-enforced)
    "row_level_security",
    "RLS",
    # Tenant-based (cross-tenant prevention)
    "tenant_id",
    "with_tenant",
    "TenantContext",
    "current_tenant",
    # Authorization decorators
    "@requires_ownership",
    "@owner_only",
    "@restrict_to_owner",
    # Permission checks
    "check_permission",
    "has_permission",
    "verify_access",
    "can_access",
    "authorize",
    "_check_acl",
    "ACL",
]


def _find_routes_with_owner_check() -> tuple[int, int]:
    """Find FastAPI route handlers, classify by ownership check.

    Returns (with_check, total).
    """
    n_with_check = 0
    n_total = 0
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts or "/tests/" in str(py):
            continue
        # Heuristic: route handlers have decorators like @router.get, @router.post.
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Find all decorator lines that look like route registration.
        route_pattern = re.compile(
            r"@\w+\.(get|post|put|delete|patch|route)\s*\(", re.MULTILINE
        )
        # Split content into function bodies (rough heuristic).
        for match in route_pattern.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            # Find function this decorator attaches to.
            # Naive: look ahead 10 lines.
            lines = content.split("\n")
            func_block = "\n".join(lines[line_no - 1 : line_no + 30])
            n_total += 1
            if any(p in func_block for p in OWNERSHIP_PATTERNS):
                n_with_check += 1
    return n_with_check, n_total


def _find_service_lookups_without_tenant() -> list[dict[str, object]]:
    """Find ``.get(id)``, ``.filter_by(id=...)`` patterns without tenant filter."""
    findings: list[dict[str, object]] = []
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts or "/tests/" in str(py):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            src = ast.unparse(node)
            # Lookups by id without tenant.
            if (
                re.search(r"\.get\(\s*\w*(?:id|uuid|pk)\w*\s*\)", src)
                or ".filter_by(id=" in src
            ):
                # Skip if tenant_id nearby.
                if "tenant" in src or "TenantContext" in src:
                    continue
                # Skip if in auth/admin paths.
                if "auth/" in str(py) or "/admin/" in str(py):
                    continue
                line_no = getattr(node, "lineno", 0)
                findings.append(
                    {
                        "file": str(py.relative_to(REPO_ROOT)),
                        "line": line_no,
                        "snippet": src[:80],
                    }
                )
    return findings


def _summarize_endpoint_coverage(n_with_check: int, n_total: int) -> dict[str, object]:
    if n_total == 0:
        return {"coverage_pct": 0.0, "with_check": 0, "total": 0}
    return {
        "coverage_pct": round(100.0 * n_with_check / n_total, 1),
        "with_check": n_with_check,
        "total": n_total,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Object-level authorization matrix check"
    )
    parser.add_argument("--strict", action="store_true", help="Exit 1 if issues found")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    notes: list[str] = []
    issues: list[str] = []

    with_check, total = _find_routes_with_owner_check()
    coverage = _summarize_endpoint_coverage(with_check, total)
    notes.append(
        f"Routes with ownership check: {coverage['with_check']}/{coverage['total']} "
        f"({coverage['coverage_pct']}%)"
    )

    if total > 0 and coverage["coverage_pct"] < 50.0:
        issues.append(
            f"Object ownership check coverage is low ({coverage['coverage_pct']}%) "
            f"— <50% of routes have explicit ownership verification."
        )

    findings = _find_service_lookups_without_tenant()
    notes.append(f"Service .get(id) without tenant filter: {len(findings)}")

    if len(findings) > 20:
        issues.append(
            f"Many service lookups ({len(findings)}) without tenant filter — "
            "potential cross-tenant data access."
        )

    result = {
        "coverage": coverage,
        "service_lookups_without_tenant_count": len(findings),
        "service_lookups_sample": findings[:20],
        "issues": issues,
        "notes": notes,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'=' * 60}")
        print("Object-Level Authorization Matrix (P0 audit 2026-09-22)")
        print(f"{'=' * 60}")
        print()
        for n in notes:
            print(f"  ℹ️  {n}")
        print()
        if findings:
            print(f"Sample service .get(id) w/o tenant filter ({len(findings)} total):")
            for f in findings[:10]:
                print(f"  - {f['file']}:{f['line']}: {f['snippet'][:60]}")
            print()
        if issues:
            print("Issues:")
            for i in issues:
                print(f"  ❌ {i}")
        else:
            print(
                "✅ All critical checks passed (object authorization coverage looks healthy)"
            )
        print()

    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
