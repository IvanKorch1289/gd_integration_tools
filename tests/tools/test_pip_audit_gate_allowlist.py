"""D-AUDIT-10301: regression-тест allowlist loading в pip_audit_gate.

Бывший баг (DEPENDENCIES-P0-001): 4-way drift между
  - .security/pip-audit-allowlist.txt (27 entries, canonical)
  - .github/workflows/security.yml (inline --ignore-vuln: 2)
  - .gitlab/ci/.gitlab-ci.yml (inline --ignore-vuln: 1)
  - tools/pip_audit_gate.py (hardcoded IGNORED_VULNS: 0)

Раньше: gate использовал hardcoded (пустой) allowlist, поэтому все 27
allowlist entries не работали — fail-OPEN.

Фикс (cycle 103): _load_allowlist() читает .security/pip-audit-allowlist.txt
at runtime, gate использует loaded IDs.
"""

from __future__ import annotations

from pathlib import Path

from tools.pip_audit_gate import (
    _CANONICAL_ALLOWLIST,
    _load_allowlist,
    IGNORED_VULNS,
)


def test_canonical_allowlist_exists() -> None:
    """Canonical allowlist файл должен существовать в репо."""
    assert _CANONICAL_ALLOWLIST.exists(), (
        f"Canonical allowlist {_CANONICAL_ALLOWLIST} not found; "
        f"gate cannot enforce security policy without it"
    )


def test_load_allowlist_returns_nonempty_set() -> None:
    """_load_allowlist() должен вернуть non-empty frozenset (27+ entries)."""
    ids = _load_allowlist()
    assert len(ids) > 0, (
        f"Allowlist loaded 0 entries from {_CANONICAL_ALLOWLIST}; "
        f"all CVEs would be reported as unignored → fail-OPEN"
    )
    assert len(ids) >= 20, (
        f"Expected at least 20 allowlist entries, got {len(ids)}. "
        f"Canonical allowlist may have been pruned — verify "
        f".security/pip-audit-allowlist.txt"
    )


def test_load_allowlist_contains_cve_ids() -> None:
    """Loaded allowlist должен содержать CVE ID (CVE-..., GHSA-..., PYSEC-...)."""
    ids = _load_allowlist()
    cve_count = sum(1 for cve_id in ids if cve_id.startswith("CVE-"))
    ghsa_count = sum(1 for cve_id in ids if cve_id.startswith("GHSA-"))
    pysec_count = sum(1 for cve_id in ids if cve_id.startswith("PYSEC-"))
    total = cve_count + ghsa_count + pysec_count
    assert total == len(ids), (
        f"Loaded {len(ids)} IDs but {cve_count}+{ghsa_count}+{pysec_count}={total} "
        f"match CVE/GHSA/PYSEC pattern. Check allowlist format."
    )


def test_load_allowlist_ignores_comments() -> None:
    """Строки начинающиеся с '#' должны игнорироваться."""
    tmp = Path(".security/test-allowlist.tmp")
    try:
        tmp.write_text(
            "# Header comment\n"
            "CVE-2024-0001\n"
            "  # Indented comment\n"
            "CVE-2024-0002  # inline comment\n"
            "\n"
            "CVE-2024-0003\n"
        )
        import tools.pip_audit_gate as gate_mod

        original = gate_mod._CANONICAL_ALLOWLIST
        gate_mod._CANONICAL_ALLOWLIST = tmp
        try:
            ids = gate_mod._load_allowlist()
        finally:
            gate_mod._CANONICAL_ALLOWLIST = original
        assert ids == frozenset({"CVE-2024-0001", "CVE-2024-0002", "CVE-2024-0003"})
    finally:
        if tmp.exists():
            tmp.unlink()


def test_legacy_fallback_when_allowlist_missing() -> None:
    """Если файл отсутствует, gate использует hardcoded IGNORED_VULNS."""
    import tools.pip_audit_gate as gate_mod

    original = gate_mod._CANONICAL_ALLOWLIST
    gate_mod._CANONICAL_ALLOWLIST = Path(".security/does-not-exist.txt")
    try:
        ids = gate_mod._load_allowlist()
    finally:
        gate_mod._CANONICAL_ALLOWLIST = original
    # Hardcoded fallback is empty frozenset
    assert ids == IGNORED_VULNS
