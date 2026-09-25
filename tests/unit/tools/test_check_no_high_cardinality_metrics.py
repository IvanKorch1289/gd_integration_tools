"""Meta-test: check_no_high_cardinality_metrics AST gate (audit W9).

Per audit W9: «Запретить tenant_id, user_id, raw route parameters и
schedule UUID как Prometheus labels. Их можно помещать в traces/logs с
policy-controlled hashing. Добавить cardinality test и budget на
unique label values».

Контракт:
1. FORBIDDEN labels (tenant_id, user_id, etc.) → FAIL on NEW additions;
2. WARNING labels (unknown labels) → log but НЕ block;
3. ALLOWED labels (status, method, etc.) → no findings;
4. Baseline фиксирует существующие labels (для backward compat).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = (
    PROJECT_ROOT / ".baselines" / "high_cardinality_metrics_baseline.json"
)


def _run_gate(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/checks/check_no_high_cardinality_metrics.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _add_finding_and_restore() -> bool:
    """Adds NEW FORBIDDEN label, runs --strict, restores."""
    test_file = PROJECT_ROOT / "src" / "backend" / "_test_high_card_metrics.py"
    try:
        test_file.write_text(
            "from prometheus_client import Counter\n"
            "c = Counter('test', 'desc', ['tenant_id'])\n"
            "c.labels(tenant_id='t1').inc()\n"
        )
        result = _run_gate(["--strict"])
        return result.returncode
    finally:
        if test_file.exists():
            test_file.unlink()
        # Restore baseline if new FORBIDDEN finding was added.
        _run_gate(["--update-baseline"])


def test_strict_gate_detects_new_forbidden_label() -> None:
    """Audit W9: --strict FAILs при NEW FORBIDDEN label (tenant_id)."""
    exit_code = _add_finding_and_restore()
    assert exit_code == 1, (
        f"--strict должен FAIL при new FORBIDDEN label. Got exit_code={exit_code}"
    )


def test_strict_gate_passes_when_no_drift() -> None:
    """--strict PASSes когда baseline == current."""
    result = _run_gate(["--strict"])
    assert result.returncode == 0, (
        f"--strict должен PASS когда no NEW FORBIDDEN. Got exit_code={result.returncode}. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_baseline_file_exists() -> None:
    """Baseline файл существует (или ранее был пустым — все FORBIDDEN fixed)."""
    assert BASELINE_PATH.is_file(), f"Baseline отсутствует: {BASELINE_PATH}"
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    # Per audit W9: после fix pool_warmup.py + sla_alerting.py ВСЕ FORBIDDEN
    # tenant_id labels были удалены → baseline МОЖЕТ быть пустым (0 findings).
    forbidden = [f for f in data if f.get("severity") == "FORBIDDEN"]
    assert isinstance(forbidden, list)
    # Если 0 — это success (все high-cardinality labels fixed per audit W9).
    # Если >0 — verify each has proper reason/owner structure.
    for f in forbidden:
        assert "file" in f and "label" in f


def test_existing_tenant_id_in_pool_warmup_is_clean() -> None:
    """Production code ``src/backend/infrastructure/database/pool_warmup.py``
    БОЛЬШЕ НЕ использует ``tenant_id`` as label (audit W9 fix)."""
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    pool_warmup_findings = [
        f for f in data
        if "pool_warmup" in f["file"] and f.get("severity") == "FORBIDDEN"
    ]
    assert pool_warmup_findings == [], (
        f"pool_warmup.py должен НЕ flag'ить tenant_id labels "
        f"(audit W9 fix перенёс в structured logging). "
        f"Found: {pool_warmup_findings}"
    )


def test_json_output_schema() -> None:
    """--json output имеет schema с forbidden counts."""
    result = _run_gate(["--json"])
    data = json.loads(result.stdout)
    assert "forbidden_baseline_count" in data
    assert "forbidden_current_count" in data
    assert "new_forbidden" in data
    assert "removed_forbidden" in data
    assert "warning_count" in data
    assert "status" in data
    assert data["status"] in ("PASS", "FAIL")


def test_warning_labels_not_blocking() -> None:
    """WARNING labels (heuristic) НЕ блокируют --strict."""
    # Добавляем file с WARNING label (не в FORBIDDEN, не в ALLOWED).
    test_file = PROJECT_ROOT / "src" / "backend" / "_test_high_card_warning.py"
    try:
        test_file.write_text(
            "from prometheus_client import Counter\n"
            "c = Counter('test', 'desc', ['some_arbitrary_metric_label'])\n"
            "c.labels(some_arbitrary_metric_label='x').inc()\n"
        )
        result = _run_gate(["--strict"])
        # --strict должен PASS (WARNING не блокирует).
        assert result.returncode == 0, (
            f"WARNING label НЕ должен блокировать. Got exit_code={result.returncode}"
        )
    finally:
        if test_file.exists():
            test_file.unlink()
        _run_gate(["--update-baseline"])


def test_update_baseline_writes_file() -> None:
    """--update-baseline writes baseline file (atomic operation)."""
    result = _run_gate(["--update-baseline"])
    assert result.returncode == 0
    assert BASELINE_PATH.is_file()
