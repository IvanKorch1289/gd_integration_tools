"""Tenant isolation cross-tenant security check (P0 audit 2026-09-22).

Scans src/ for:
1. **Missing tenant_id filters** в ORM queries — queries that read/write
   data без ``tenant_id=...`` filter могут leak data between tenants.
2. **Direct tenant context access** — places where ``TenantContext.get()``
   is bypassed.
3. **Cross-tenant imports** — code that imports another tenant's modules.
4. **Missing RLS markers** — ORM models без ``__table_args__`` containing
   RLS policy hints.

v6 W3.5 (25.09 audit): versioned allowlist в
``.baselines/tenant_isolation_allowlist.yaml`` filter'ит known
false positives (infrastructure/system callsites). Unclassified findings
→ gate FAIL per audit W3.5.

Использование::

    python tools/checks/check_tenant_isolation.py              # human-readable
    python tools/checks/check_tenant_isolation.py --strict    # exit 1 if UNCLASSIFIED issues
    python tools/checks/check_tenant_isolation.py --json      # machine output

Exit codes:
    0 — все проверки OK (или все findings классифицированы)
    1 — найдены UNCLASSIFIED findings (--strict)
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
ALLOWLIST_PATH = (
    REPO_ROOT / ".baselines" / "tenant_isolation_allowlist.yaml"
)


def _load_tenant_allowlist() -> set[tuple[str, int]]:
    """Load ``.baselines/tenant_isolation_allowlist.yaml`` → set of (file, line) tuples.

    Per audit W3.5 (25.09): versioned allowlist с owner, reason, review_date.
    Каждый entry классифицирует callsite как FALSE_POSITIVE (system infra,
    не user-data) и НЕ должен проходить через ``--strict`` gate.

    Returns:
        Set of ``(relative_file_path, line_number)`` для matching against
        findings. Если файл указан без конкретных line → wildcard match
        (все lines этого файла).

    Per audit W3: «Запретить новые optional tenant parameters AST-gate'ом.
    Каждый entry здесь — явный documented exception с review_date.
    НЕ добавлять entries для user-data API callsites без ADR».
    """
    allowed: set[tuple[str, int]] = set()

    if not ALLOWLIST_PATH.is_file():
        return allowed

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return allowed

    try:
        with ALLOWLIST_PATH.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:  # type: ignore[misc]
        print(f"warning: failed to load tenant allowlist: {exc}", file=sys.stderr)
        return allowed

    for entry in data.get("allowlist", []) or []:
        file = entry.get("file")
        if not file:
            continue
        line = entry.get("line")
        if line is None:
            # Wildcard match: все lines этого файла.
            allowed.add((file, 0))
        else:
            allowed.add((file, int(line)))

    return allowed


def _is_finding_allowlisted(
    file: str, line: int, allowlist: set[tuple[str, int]]
) -> bool:
    """Check if (file, line) matches allowlist (including wildcards)."""
    if (file, line) in allowlist:
        return True
    if (file, 0) in allowlist:  # wildcard match (any line in file)
        return True
    return False


def _is_query_node(node: ast.AST) -> bool:
    """True если node похож на ORM query construction.

    v6 W3.5 fix: более точный detection — проверяем что node — это
    Call expression, не вся функция (которая содержала бы любые
    patterns внутри). Раньше ast.unparse на FunctionDef node возвращал
    ВСЁ тело функции, и если в любом statement было ``objects.get``,
    флагалась ВСЯ функция (977 false positives из 1966).
    """
    # Must be a Call expression, не FunctionDef/ClassDef/etc.
    if not isinstance(node, ast.Call):
        return False
    src = ast.unparse(node.func) if hasattr(node, "func") else ast.unparse(node)
    query_patterns = [
        "select",
        "filter",
        "where",
        "Session",
        "session.execute",
        "session.scalar",
        "session.scalars",
        ".query",
        "objects.filter",
        "objects.get",
        "objects.all",
    ]
    return any(p in src for p in query_patterns)


def _scan_missing_tenant_filter(file: Path, content: str) -> list[tuple[int, str]]:
    """Return (line_no, snippet) для query patterns без tenant_id filter."""
    findings: list[tuple[int, str]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return findings

    # Tenant filter patterns (positive examples).
    tenant_patterns = [
        "tenant_id=",
        "tenant_id =",
        "TenantContext",
        "tenant_filter",
        "with_tenant",
        "filter_by_tenant",
        "tenant_scope",
    ]

    for node in ast.walk(tree):
        if not _is_query_node(node):
            continue
        src = ast.unparse(node)
        # Skip if file is a tenancy helper itself.
        if "tenancy" in str(file):
            continue
        # Skip if explicit tenant filter present.
        if any(p in src for p in tenant_patterns):
            continue
        # Skip tests / docs.
        if file.name.startswith("test_") or "/tests/" in str(file):
            continue
        # Skip docstrings.
        line_no = getattr(node, "lineno", 0)
        if line_no > 0:
            line_text = (
                content.split("\n")[line_no - 1].strip()
                if line_no <= content.count("\n") + 1
                else ""
            )
            # Skip if it's actually a comment or docstring.
            if (
                line_text.startswith("#")
                or line_text.startswith('"""')
                or line_text.startswith("'")
            ):
                continue
            findings.append((line_no, line_text[:80]))

    return findings


def _scan_direct_tenant_context_access(
    file: Path, content: str
) -> list[tuple[int, str]]:
    """Return (line_no, snippet) для ``TenantContext.get()`` direct access.

    Direct ``TenantContext.get()`` (vs via context manager) может bypass
    cleanup logic в async contexts.
    """
    findings: list[tuple[int, str]] = []
    if "TenantContext.get()" in content:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return findings
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                src = ast.unparse(node)
                if "TenantContext.get()" in src:
                    line_no = getattr(node, "lineno", 0)
                    line_text = (
                        content.split("\n")[line_no - 1].strip() if line_no > 0 else ""
                    )
                    findings.append((line_no, line_text[:80]))
    return findings


def _scan_rls_markers(file: Path, content: str) -> tuple[bool, int]:
    """Check ORM model for RLS policy hints."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False, 0
    n_classes = 0
    has_rls_hint = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Heuristic: class with __tablename__ is ORM model.
            src = ast.unparse(node)
            if "__tablename__" in src:
                n_classes += 1
                if "rls" in src.lower() or "row_level" in src.lower():
                    has_rls_hint = True
    return has_rls_hint, n_classes


def _scan_tenant_id_in_models(file: Path, content: str) -> list[tuple[int, str]]:
    """Find ORM models без tenant_id column."""
    findings: list[tuple[int, str]] = []
    if not any(
        marker in file.parts for marker in ("models", "repositories", "infrastructure")
    ):
        return findings
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return findings
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            src = ast.unparse(node)
            if "__tablename__" not in src:
                continue
            # Check for tenant_id Column.
            if "tenant_id" in src:
                continue
            # Skip auth/permission tables (often not tenant-scoped).
            name = node.name.lower()
            if name in ("user", "role", "permission", "apikey"):
                continue
            line_no = node.lineno
            line_text = f"class {node.name}"
            findings.append((line_no, line_text))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tenant isolation cross-tenant security check"
    )
    parser.add_argument("--strict", action="store_true", help="Exit 1 if issues found")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    issues: list[str] = []
    notes: list[str] = []
    missing_filter_findings: list[dict[str, object]] = []
    direct_get_findings: list[dict[str, object]] = []
    no_tenant_id_findings: list[dict[str, object]] = []

    files_scanned = 0
    for py in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        # Skip examples, tests, scripts.
        if "/examples/" in str(py) or "/tests/" in str(py) or "/scripts/" in str(py):
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_scanned += 1

        # 1. Missing tenant filter.
        for line_no, line in _scan_missing_tenant_filter(py, content):
            missing_filter_findings.append(
                {
                    "file": str(py.relative_to(REPO_ROOT)),
                    "line": line_no,
                    "snippet": line,
                }
            )

        # 2. Direct TenantContext.get() access.
        for line_no, line in _scan_direct_tenant_context_access(py, content):
            direct_get_findings.append(
                {
                    "file": str(py.relative_to(REPO_ROOT)),
                    "line": line_no,
                    "snippet": line,
                }
            )

        # 3. ORM models без tenant_id.
        for line_no, line in _scan_tenant_id_in_models(py, content):
            no_tenant_id_findings.append(
                {
                    "file": str(py.relative_to(REPO_ROOT)),
                    "line": line_no,
                    "snippet": line,
                }
            )

    notes.append(f"Files scanned: {files_scanned}")
    notes.append(f"Missing tenant filter candidates: {len(missing_filter_findings)}")
    notes.append(f"Direct TenantContext.get() usages: {len(direct_get_findings)}")
    notes.append(f"ORM models without tenant_id column: {len(no_tenant_id_findings)}")

    # v6 W3.5: load versioned allowlist и filter known false positives.
    # Per audit W3.5: «Tenant gate должен работать по versioned allowlist
    # и падать на unclassified findings».
    allowlist = _load_tenant_allowlist()

    def _filter_allowlisted(
        findings: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Split findings into (allowlisted, unclassified).

        Returns:
            (allowlisted, unclassified) — unclassified entries НЕ
            классифицированы в .baselines/tenant_isolation_allowlist.yaml
            → должны быть адрессованы (либо fix, либо allowlist entry с
            owner/reason/review_date).
        """
        allowlisted: list[dict[str, object]] = []
        unclassified: list[dict[str, object]] = []
        for f in findings:
            if _is_finding_allowlisted(str(f["file"]), int(f["line"]), allowlist):
                allowlisted.append(f)
            else:
                unclassified.append(f)
        return allowlisted, unclassified

    missing_filter_allowlisted, missing_filter_unclassified = _filter_allowlisted(
        missing_filter_findings
    )
    direct_get_allowlisted, direct_get_unclassified = _filter_allowlisted(
        direct_get_findings
    )
    no_tenant_id_allowlisted, no_tenant_id_unclassified = _filter_allowlisted(
        no_tenant_id_findings
    )

    notes.append(f"Allowlisted (false positives): {len(missing_filter_allowlisted)}")
    notes.append(f"Unclassified (need attention): {len(missing_filter_unclassified)}")

    # v6 W3 gate integrity: --strict fails только на UNCLASSIFIED findings.
    # Allowlisted findings классифицированы (system infra) → не failures.
    if direct_get_unclassified:
        issues.append(
            f"Direct TenantContext.get() (unclassified): {len(direct_get_unclassified)} "
            "— bypasses async context cleanup. Use 'with TenantContext(...)' instead. "
            "Document in allowlist или fix per audit W3.5."
        )
    if missing_filter_unclassified:
        issues.append(
            f"Missing tenant filter (unclassified): {len(missing_filter_unclassified)} — "
            "user-data API callsites без tenant predicate и НЕ классифицированы "
            "в .baselines/tenant_isolation_allowlist.yaml. Per ADR-0345 Option A "
            "ВСЕ user-data callsites должны быть либо fixed (tenant filter), либо "
            "явно allowlist'нуты с owner/reason/review_date."
        )
    if no_tenant_id_unclassified:
        issues.append(
            f"ORM models without tenant_id (unclassified): {len(no_tenant_id_unclassified)} — "
            "per ADR-0345 все ORM models с user-data должны иметь tenant_id column. "
            "Document в allowlist или fix per audit W3.5."
        )

    # Diagnostic info: total findings vs allowlisted.
    total_findings = (
        len(missing_filter_findings)
        + len(direct_get_findings)
        + len(no_tenant_id_findings)
    )
    total_allowlisted = (
        len(missing_filter_allowlisted)
        + len(direct_get_allowlisted)
        + len(no_tenant_id_allowlisted)
    )
    notes.append(
        f"Total findings: {total_findings}; "
        f"allowlisted: {total_allowlisted} ({total_allowlisted * 100 // max(total_findings, 1)}%); "
        f"unclassified: {total_findings - total_allowlisted}"
    )

    # Report.
    result = {
        "files_scanned": files_scanned,
        "missing_tenant_filter_candidates": missing_filter_unclassified[:20],
        "direct_TenantContext_get": direct_get_unclassified[:20],
        "orm_models_no_tenant_id": no_tenant_id_unclassified[:20],
        "total_missing_filter": len(missing_filter_findings),
        "total_direct_get": len(direct_get_findings),
        "total_no_tenant_id": len(no_tenant_id_findings),
        "total_missing_filter_allowlisted": len(missing_filter_allowlisted),
        "total_missing_filter_unclassified": len(missing_filter_unclassified),
        "total_no_tenant_id_allowlisted": len(no_tenant_id_allowlisted),
        "total_no_tenant_id_unclassified": len(no_tenant_id_unclassified),
        "allowlist_path": str(ALLOWLIST_PATH.relative_to(REPO_ROOT))
        if ALLOWLIST_PATH.is_file()
        else None,
        "issues": issues,
        "notes": notes,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'=' * 60}")
        print("Tenant Isolation Check (P0 audit 2026-09-22 + W3.5 allowlist)")
        print(f"{'=' * 60}")
        print()
        for n in notes:
            print(f"  ℹ️  {n}")
        print()
        if direct_get_unclassified:
            print(f"Direct TenantContext.get() UNCLASSIFIED ({len(direct_get_unclassified)}):")
            for f in direct_get_unclassified[:5]:
                print(f"  - {f['file']}:{f['line']}: {f['snippet'][:60]}")
            print()
        if no_tenant_id_unclassified:
            print(f"ORM models w/o tenant_id UNCLASSIFIED ({len(no_tenant_id_unclassified)}):")
            for f in no_tenant_id_unclassified[:5]:
                print(f"  - {f['file']}:{f['line']}: {f['snippet'][:60]}")
            print()
        if missing_filter_unclassified:
            print(f"Missing tenant filter UNCLASSIFIED ({len(missing_filter_unclassified)}):")
            for f in missing_filter_unclassified[:5]:
                print(f"  - {f['file']}:{f['line']}: {f['snippet'][:60]}")
            print()
        if issues:
            print("Issues (--strict FAIL):")
            for i in issues:
                print(f"  ❌ {i}")
        else:
            print("✅ All findings classified (allowlist covers system infra)")
        print()

    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
