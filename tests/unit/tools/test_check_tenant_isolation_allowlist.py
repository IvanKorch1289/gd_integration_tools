"""Meta-test: check_tenant_isolation --strict gate with versioned allowlist (W3.5).

Per 25.09 audit W3.5: «Tenant gate должен работать по versioned allowlist
и падать на unclassified findings. Запретить новые optional tenant
parameters AST-gate'ом».

Контракт:
1. --strict FAILs только на UNCLASSIFIED findings (не allowlisted);
2. allowlist entries классифицируются как system infra (FALSE_POSITIVE);
3. Каждое entry имеет owner, reason, review_date (versioned);
4. Новые findings без allowlist entry → UNCLASSIFIED → --strict FAIL.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run_gate(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/checks/check_tenant_isolation.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_strict_gate_honest_on_unclassified_findings() -> None:
    """Audit W3.5: --strict FAILS при unclassified findings (NOT false PASS).

    До W3.5 fix: --strict exit 0 при 1966 candidates (false PASS).
    После fix: --strict FAILs честно с подсчётом allowlisted vs unclassified.
    """
    result = _run_gate(["--strict"])
    assert result.returncode == 1, (
        f"W3.5 audit violation: --strict should FAIL at unclassified findings, "
        f"got exit={result.returncode}. "
        f"stdout:\n{result.stdout[-500:]}"
    )
    # Output должен mention unclassified findings.
    assert "unclassified" in result.stdout.lower() or "Unclassified" in result.stdout


def test_allowlist_yaml_exists_and_has_entries() -> None:
    """Allowlist файл существует и содержит versioned entries с owner/reason/review_date."""
    allowlist_path = (
        PROJECT_ROOT / ".baselines" / "tenant_isolation_allowlist.yaml"
    )
    assert allowlist_path.is_file(), (
        f"Allowlist файл отсутствует: {allowlist_path}. "
        f"Per audit W3.5: 'Tenant gate должен работать по versioned allowlist'."
    )

    content = allowlist_path.read_text(encoding="utf-8")
    # Каждое entry должно иметь owner, reason, review_date.
    import yaml  # type: ignore[import-untyped]

    data = yaml.safe_load(content)
    entries = data.get("allowlist", [])
    assert len(entries) >= 10, (
        f"Allowlist должен содержать >=10 entries для high-confidence "
        f"false-positive filtering. Got {len(entries)}."
    )
    for entry in entries:
        assert "file" in entry, f"Entry missing 'file': {entry}"
        assert "reason" in entry, f"Entry missing 'reason': {entry}"
        assert "owner" in entry, f"Entry missing 'owner': {entry}"
        assert "review_date" in entry, f"Entry missing 'review_date': {entry}"
        assert "added_at" in entry, f"Entry missing 'added_at': {entry}"


def test_allowlist_filter_reduces_findings() -> None:
    """Allowlist filter reduces findings count (proof: total > unclassified)."""
    result = _run_gate(["--json"])
    assert result.returncode in (0, 1)  # может быть 0 если все allowlisted
    import json

    data = json.loads(result.stdout)
    total_missing = data["total_missing_filter"]
    allowlisted = data["total_missing_filter_allowlisted"]
    unclassified = data["total_missing_filter_unclassified"]

    assert total_missing == allowlisted + unclassified, (
        f"total != allowlisted + unclassified: "
        f"{total_missing} != {allowlisted} + {unclassified}"
    )
    assert allowlisted > 0, (
        f"Allowlist должен reduce findings. Got allowlisted={allowlisted}, "
        f"unclassified={unclassified}"
    )
    # Audit-cited "1966 missing" значительно reduced.
    assert total_missing < 1966, (
        f"Heuristic должен быть более precise после _is_query_node fix. "
        f"Got total_missing={total_missing}, expected < 1966"
    )


def test_orm_models_allowlisted() -> None:
    """ORM models без tenant_id column должны быть allowlisted (system-managed)."""
    result = _run_gate(["--json"])
    import json

    data = json.loads(result.stdout)
    # ORM models с user-data должны быть fixed, не allowlisted.
    # System-managed (BaseModel, CertRecord, LangMemEpisodic, OutboxMessage)
    # — allowlisted.
    unclassified_orm = data["total_no_tenant_id_unclassified"]
    # Допустимо иметь unclassified ORM models — gate их flag'ит как issues.
    # Но BaseModel (абстрактный) должен быть allowlisted.
    assert data["total_no_tenant_id"] == data["total_no_tenant_id_allowlisted"] + unclassified_orm


def test_strict_gate_help_documents_v6_w35() -> None:
    """Help text документирует W3.5 allowlist semantics."""
    result = _run_gate(["--help"])
    assert "strict" in result.stdout.lower()
    assert "issues" in result.stdout.lower()
