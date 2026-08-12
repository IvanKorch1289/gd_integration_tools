#!/usr/bin/env python3
"""pip-audit CI gate — exits non-zero if unignored vulnerabilities found.

S29 W1: pip-audit 2.10.0 always exits 0 even with vulnerabilities.
This wrapper parses JSON output and enforces the gate properly.

D-AUDIT-10301 fix (cycle 103, DEPENDENCIES-P0-001): canonical allowlist
теперь LOADED from ``.security/pip-audit-allowlist.txt`` at runtime
— eliminates 4-way drift между:
  - .security/pip-audit-allowlist.txt (canonical source, 27 IDs)
  - .github/workflows/security.yml (inline --ignore-vuln)
  - .gitlab/ci/.gitlab-ci.yml (inline --ignore-vuln)
  - tools/pip_audit_gate.py (hardcoded IGNORED_VULNS, ранее пустой)

Раньше: каждый CI path использовал свой subset allowlist → drift.
Теперь: canonical source of truth = allowlist.txt, gate loads from it
на startup. CI workflows остаются source для inline-ignore при первом
scan (output JSON), но gate делает final decision через allowlist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Canonical allowlist path. Если файл отсутствует — gate использует
# hardcoded IGNORED_VULNS (legacy fallback, 0 entries по умолчанию).
_CANONICAL_ALLOWLIST = Path(".security/pip-audit-allowlist.txt")

# Hardcoded fallback. Loaded from allowlist.txt at runtime (см. _load_allowlist).
# Оставлен для backward compat — если файл отсутствует, gate работает
# как раньше (без ignores).
IGNORED_VULNS: frozenset[str] = frozenset(
    [
        # D-AUDIT-10201 fix (cycle 102, DEPENDENCIES-P0-004): removed
        # СТАРЫЙ комментарий "CVE-2025-69872 (diskcache) REMOVED in
        # s170 — diskcache dependency eliminated" — это НЕВЕРНО.
        # Фактчек 2026-08-11: diskcache 5.6.3 всё ещё установлен и
        # используется (src/backend/infrastructure/decorators/caching/
        # storage/disk.py).
    ]
)


def _load_allowlist() -> frozenset[str]:
    """Загрузить canonical allowlist из .security/pip-audit-allowlist.txt.

    D-AUDIT-10301 fix (cycle 103): один source of truth вместо
    hardcoded + inline-ignore drift.

    Формат файла: одна CVE ID на строку (CVE-..., GHSA-..., PYSEC-...).
    Пустые строки и строки начинающиеся с '#' игнорируются.
    Поддержка inline-комментариев: 'CVE-...  # comment'.
    """
    if not _CANONICAL_ALLOWLIST.exists():
        print(
            f"WARN: canonical allowlist {_CANONICAL_ALLOWLIST} not found; "
            f"using hardcoded IGNORED_VULNS ({len(IGNORED_VULNS)} entries)",
            file=sys.stderr,
        )
        return IGNORED_VULNS

    ids: set[str] = set()
    try:
        for line in _CANONICAL_ALLOWLIST.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Поддержка inline-комментариев: 'CVE-...  # comment'
            cve_id = stripped.split("#", 1)[0].strip()
            if cve_id:
                ids.add(cve_id)
    except OSError as exc:
        print(
            f"WARN: failed to read {_CANONICAL_ALLOWLIST}: {exc}; "
            f"using hardcoded IGNORED_VULNS",
            file=sys.stderr,
        )
        return IGNORED_VULNS

    return frozenset(ids)


def main() -> None:
    """Run pip-audit gate — exits non-zero на empty/invalid JSON или unignored vulns.

    D-AUDIT-11-1 fix (cycle 1): добавлена явная проверка non-empty ``dependencies``.
    Без этого gate возвращал PASS для ``{"dependencies": []}`` (валидный JSON
    без actual deps), что позволяло CVE от доработок проходить без блокировки.

    D-AUDIT-10301 fix (cycle 103, DEPENDENCIES-P0-001): allowlist loaded
    from canonical source (.security/pip-audit-allowlist.txt) at startup.
    """
    # D-AUDIT-10301: load canonical allowlist вместо hardcoded IGNORED_VULNS.
    ignored = _load_allowlist()
    print(f"Allowlist loaded: {len(ignored)} entries from {_CANONICAL_ALLOWLIST}")

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
            if vuln_id in ignored:
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
