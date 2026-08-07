#!/usr/bin/env python3
"""pip-audit CI gate — exits non-zero if unignored vulnerabilities found.

S29 W1: pip-audit 2.10.0 always exits 0 even with vulnerabilities.
This wrapper parses JSON output and enforces the gate properly.

# cycle-3/D-AUDIT-02: 8 stale CVE удалены per phase-3/C3-02 (DEPS-P0-001).
# PYSEC-2026-87 (lxml) удалён из IGNORED_VULNS ниже — installed lxml уже
# содержит fix. Остальные 7 ID удалены из .security/pip-audit-allowlist.txt
# (PYSEC-2026-161 starlette, CVE-2026-46645 sqladmin, CVE-2026-45739
# strawberry-graphql, GHSA-mv93-w799-cj2w gitpython, PYSEC-2026-142/141
# urllib3, CVE-2026-45409 idna — все fix closed в installed versions).
# Hardcoded IGNORED_VULNS сводится к пустому frozenset — все игноры
# теперь живут только в allowlist.txt (canonical source of truth).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# cycle-3/D-AUDIT-02: PYSEC-2026-87 (lxml) удалён — installed lxml ≥ fix;
# canonical allowlist живёт в .security/pip-audit-allowlist.txt.
IGNORED_VULNS: frozenset[str] = frozenset(
    [
        # NOTE: PYSEC-2026-161 (starlette) FIXED in s30/w1 - starlette 1.1.0
        # NOTE: CVE-2025-69872 (diskcache) REMOVED in s170 — diskcache
        # dependency eliminated; replaced with custom JSONDisk cache.
    ]
)


def main() -> None:
    """Run pip-audit gate — exits non-zero on empty/invalid JSON или unignored vulns.

    D-AUDIT-11-1 fix (cycle 1): добавлена явная проверка non-empty ``dependencies``.
    Без этого gate возвращал PASS для ``{"dependencies": []}`` (валидный JSON
    без actual deps), что позволяло CVE от доработок проходить без блокировки.
    """
    json_path = Path("pip-audit.json")
    if not json_path.exists():
        print("ERROR: pip-audit.json not found", file=sys.stderr)
        sys.exit(1)

    try:
        with json_path.open() as f:
            report = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"ERROR: pip-audit.json malformed JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    # D-AUDIT-11-1 fix (cycle 1): enforce non-empty dependencies — fail-CLOSED.
    # Без этой проверки {"dependencies": []} проходит как PASS, маскируя
    # реальные CVE от новых зависимостей (silent fail-OPEN security gate).
    if not isinstance(report, dict) or not report.get("dependencies"):
        print(
            "ERROR: pip-audit.json has no 'dependencies' key or empty list. "
            "Gate FAIL-CLOSED — regenerate via `make audit-deps` "
            "or `uv run pip-audit --format json --output pip-audit.json`.",
            file=sys.stderr,
        )
        sys.exit(1)

    dependencies = report.get("dependencies", [])
    vuln_count = 0
    vuln_packages: list[str] = []

    for dep in dependencies:
        vulns = dep.get("vulns", [])
        if not vulns:
            continue
        for vuln in vulns:
            vuln_id = vuln.get("id", "")
            if vuln_id in IGNORED_VULNS:
                print(f"IGNORED: {dep['name']} {vuln_id}")
                continue
            print(
                f"VULN: {dep['name']} {vuln_id} — fix available: {vuln.get('fix_versions', [])}"
            )
            vuln_count += 1
            if dep["name"] not in vuln_packages:
                vuln_packages.append(dep["name"])

    if vuln_count > 0:
        print(
            f"\nFAIL: {vuln_count} unignored vulnerabilities in {len(vuln_packages)} packages"
        )
        print("Update dependencies to fix versions to pass the gate.")
        sys.exit(1)

    print("\nPASS: 0 unignored vulnerabilities")
    sys.exit(0)


if __name__ == "__main__":
    main()
