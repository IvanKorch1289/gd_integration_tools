#!/usr/bin/env python3
"""pip-audit CI gate — exits non-zero if unignored vulnerabilities found.

S29 W1: pip-audit 2.10.0 always exits 0 even with vulnerabilities.
This wrapper parses JSON output and enforces the gate properly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


IGNORED_VULNS: frozenset[str] = frozenset([
    "CVE-2025-69872",  # diskcache pickle RCE, no fix version
    # S29 W2 carryover — dependency constraints, NOT unfixable:
    "PYSEC-2026-87",   # lxml: fix 6.1.0 available but no Python 3.14 wheels
    "PYSEC-2026-161",  # starlette: fix 1.0.1 available but prometheus-fastapi-instrumentator blocks upgrade
])


def main() -> None:
    json_path = Path("pip-audit.json")
    if not json_path.exists():
        print("ERROR: pip-audit.json not found", file=sys.stderr)
        sys.exit(1)

    with json_path.open() as f:
        report = json.load(f)

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
            print(f"VULN: {dep['name']} {vuln_id} — fix available: {vuln.get('fix_versions', [])}")
            vuln_count += 1
            if dep["name"] not in vuln_packages:
                vuln_packages.append(dep["name"])

    if vuln_count > 0:
        print(f"\nFAIL: {vuln_count} unignored vulnerabilities in {len(vuln_packages)} packages")
        print("Update dependencies to fix versions to pass the gate.")
        sys.exit(1)

    print(f"\nPASS: 0 unignored vulnerabilities")
    sys.exit(0)


if __name__ == "__main__":
    main()
