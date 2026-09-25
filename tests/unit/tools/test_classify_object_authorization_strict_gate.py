"""Meta-test: classify_object_authorization --strict gate (v6 W1).

Per v6 W1: «Object classifier strict должен падать при `unknown > 0`».
Gate MUST exit non-zero при любом unknown callsite (не threshold 20% как
раньше — скрывало 23 unknown).

Regression guard: тест запускает script как subprocess + проверяет exit
code + stderr message. Если кто-то ослабит strict gate (revert на 20%
threshold) — тест упадёт.

v6 W3.5 update: PATH_USER_DATA_PATTERNS теперь классифицирует
``self.get(id)`` в notebooks_mongo.py / rag_ingest_store.py /
webhook_scheduler.py как user-data (НЕ unknown) → gate PASSES.
Все 5 бывших unknown callsites получили path-based USER_DATA detection.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run_strict() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/classify_object_authorization.py", "--strict"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_strict_gate_passes_when_all_classified() -> None:
    """v6 W1+W3.5: gate PASSES когда все callsites классифицированы (0 unknown).

    Per v6 W3.5: PATH_USER_DATA_PATTERNS extension reclassifies 5 former
    UNKNOWN callsites в notebooks_mongo.py / rag_ingest_store.py /
    webhook_scheduler.py как user-data. Gate должен проходить.
    """
    result = _run_strict()

    assert result.returncode == 0, (
        f"strict gate FAILED (exit={result.returncode}) but должен PASS "
        f"после v6 W3.5 path-based classification. "
        f"stdout tail:\n{result.stdout[-500:]}\n"
        f"stderr:\n{result.stderr[-500:]}"
    )

    # stderr содержит OK message (v6 W1 strict gate OK format).
    assert "strict gate OK" in result.stderr, (
        f"strict gate passed but stderr missing 'strict gate OK' message:\n"
        f"stderr:\n{result.stderr[-500:]}"
    )

    # Парсим число unknown callsites для sanity-check (должно быть 0).
    match = re.search(r"unknown:\s+(\d+)", result.stdout)
    assert match is not None, f"cannot parse unknown count: {result.stdout}"
    n_unknown = int(match.group(1))
    assert n_unknown == 0, (
        f"strict gate passed but parsed {n_unknown} unknown callsites — "
        f"PATH_USER_DATA_PATTERNS regression. stdout:\n{result.stdout[-500:]}"
    )

    # Также проверяем, что user-data >= 9 (после 25.09 audit).
    # Pre-25.09: 14 (9 baseline + 5 path-based для notebooks/rag/webhook).
    # Post-25.09: webhook/notebooks/RAG все resolved через actual tenant filter,
    # → user-data count снизился до 9. PATH_USER_DATA_PATTERNS остаётся
    # как safety-net для re-classification.
    match_ud = re.search(r"user-data:\s+(\d+)", result.stdout)
    assert match_ud is not None, f"cannot parse user-data count: {result.stdout}"
    n_user_data = int(match_ud.group(1))
    assert n_user_data >= 9, (
        f"expected user-data >= 9, got {n_user_data} — "
        f"PATH_USER_DATA_PATTERNS regression. stdout:\n{result.stdout[-500:]}"
    )


def test_path_user_data_patterns_is_optional_safety_net() -> None:
    """v6 W3.5 + 25.09 audit: PATH_USER_DATA_PATTERNS — safety-net, не критичный.

    После 25.09 audit fix WebhookScheduler / MongoNotebookRepository /
    RAG ingest store — все 5 callsites теперь classified корректно через
    actual tenant filter (не через path-based heuristic). Удаление
    PATH_USER_DATA_PATTERNS не должно ломать gate.

    Этот тест документирует, что safety-net можно безопасно удалить в
    будущем (W4 cleanup), но оставлен на случай новых user-data paths.
    """
    code = """
import sys
sys.path.insert(0, 'tools')
import classify_object_authorization as c
# Monkeypatch: пустые паттерны → проверяем что gate всё ещё PASSES.
c.PATH_USER_DATA_PATTERNS = ()
callsites = c.collect_all_callsites()
unknowns = [cs for cs in callsites if cs.receiver_type == 'unknown']
print(f'unknown={len(unknowns)}', file=sys.stderr)
sys.exit(1 if unknowns else 0)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    # После 25.09 fix: removing PATH_USER_DATA_PATTERNS НЕ должно ломать gate.
    # 5 бывших path-based callsites теперь resolved через actual tenant_id в коде.
    assert result.returncode == 0, (
        f"PATH_USER_DATA_PATTERNS safety-net теперь redundant (0 unknown "
        f"без паттернов после 25.09 tenant-id hard-code). "
        f"stderr:\n{result.stderr[-500:]}"
    )

    # Парсим unknown count — должен быть 0 (все resolved).
    match = re.search(r"unknown=(\d+)", result.stderr)
    assert match is not None, f"cannot parse unknown count: {result.stderr}"
    n_unknown = int(match.group(1))
    assert n_unknown == 0, (
        f"expected 0 unknown without PATH_USER_DATA_PATTERNS "
        f"(all resolved via 25.09 tenant-id hard-code), "
        f"got {n_unknown}. stderr:\n{result.stderr[-500:]}"
    )


def test_strict_gate_help_documents_v6_thresholds() -> None:
    """Help text должен document новый v6 порог (unknown > 0)."""
    result = subprocess.run(
        [sys.executable, "tools/classify_object_authorization.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "unknown" in result.stdout.lower()
    # Per v6 W1 — gate должен block на unknown > 0 (НЕ threshold 20%).
    assert "20" not in result.stdout or "v6" in result.stdout, (
        "Help text references 20% threshold (deprecated per v6 W1)"
    )
