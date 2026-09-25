"""Meta-test: check_dsl_processors_imports --strict gate (v6 W4 / 25.09 audit).

Per v6 §10 W4 + 25.09 audit: «Добавить AST-gate, запрещающий новые импорты
src.backend.dsl.processors». Этот gate предотвращает появление нового долга
после миграции 3 legacy mixin (PlanExecute, ReflectionLoop, RouterSpecialist)
в canonical ``dsl.engine.processors``.

Контракт:
- ``--strict`` exits 0 когда нет violations;
- ``--strict`` exits 1 когда есть violations вне allowlist;
- Временный allowlist (3 lines в builders/base/__init__.py) — для Sprint 7
  миграции. После миграции allowlist обнуляется.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run_gate(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/checks/check_dsl_processors_imports.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_strict_gate_passes_when_no_violations() -> None:
    """v6 W4: gate exits 0 когда нет violations вне allowlist."""
    result = _run_gate(["--strict"])
    assert result.returncode == 0, (
        f"AST-gate FAILED (exit={result.returncode}) but expected PASS "
        f"после 25.09 audit (3 allowlist entries в builders/base/__init__.py). "
        f"stdout:\n{result.stdout[-500:]}\nstderr:\n{result.stderr[-500:]}"
    )


def test_strict_gate_fails_on_new_forbidden_import() -> None:
    """Regression guard: новый импорт src.backend.dsl.processors.* → exit 1.

    Создаём временный файл с forbidden import, запускаем gate,
    проверяем exit 1 + наличие violation в выводе.
    """
    test_file = PROJECT_ROOT / "src/backend/_test_dsl_proc_gate_violation.py"
    test_file.write_text(
        "from src.backend.dsl.processors.plan_execute_processor import "
        "PlanExecuteMixin\n"
    )
    try:
        result = _run_gate(["--strict"])
        assert result.returncode != 0, (
            f"AST-gate PASSED but expected FAIL после создания "
            f"forbidden import file. stdout:\n{result.stdout[-500:]}"
        )
        # Stdout должен содержать violation в таблице.
        assert "_test_dsl_proc_gate_violation" in result.stdout, (
            f"AST-gate failed but stdout missing test file in violations: "
            f"{result.stdout[-500:]}"
        )
    finally:
        test_file.unlink(missing_ok=True)


def test_allowlist_is_empty_after_legacy_migration() -> None:
    """25.09 audit: 3 legacy mixin мигрированы в canonical — allowlist пуст.

    Per v6 W4 + 25.09 audit: PlanExecute / ReflectionLoop / RouterSpecialist
    mixin мигрированы из ``dsl/builders/base/__init__.py`` в canonical
    ``dsl/engine/processors/<name>.py``. Allowlist обнулён.

    Если в будущем кто-то добавит новый импорт из legacy branch —
    AST-gate поймает это через violations_count > 0.
    """
    result = _run_gate(["--json"])
    assert result.returncode == 0
    import json

    payload = json.loads(result.stdout)
    assert payload["allowlist_size"] == 0, (
        f"expected 0 allowlist entries после 25.09 миграции, "
        f"got {payload['allowlist_size']}. Если появились новые legacy "
        f"imports — мигрируйте их в canonical и обнулите allowlist."
    )
    assert payload["violations_count"] == 0, (
        f"expected 0 violations, got {payload['violations_count']}: "
        f"{payload['violations']}"
    )
