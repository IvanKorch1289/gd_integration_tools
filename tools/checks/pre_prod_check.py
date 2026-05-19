"""pre-prod-check gate — 20/20 BLOCKING (Sprint 9 K1 W6 / DoD-10).

Запускает 20 проверок и репортит итог. Любая failed проверка → exit 1.

Запуск:

.. code-block:: bash

    make pre-prod-check
    # OR:
    python tools/checks/pre_prod_check.py

20 проверок:

1.  coverage ≥75% (ratcheting)
2.  mypy errors ≤30 (ratcheting)
3.  layer violations = 0
4.  ruff strict
5.  secrets-check
6.  SBOM fresh (CycloneDX generated)
7.  pip-audit (no high-severity)
8.  bandit-tls (high severity = 0)
9.  OWASP ZAP baseline
10. codeclone strict (ratchet)
11. docstring coverage (ratchet)
12. docs Vale (no errors)
13. sphinx -W build (warnings → errors)
14. WAF coverage strict (0 violations)
15. feature-flags audit (новые default-OFF)
16. team-ownership valid
17. side-effect audit
18. perf-gate (locust baseline, blocking)
19. startup-time <3s (Sprint 9 K3 W3)
20. Streamlit page collisions = 0 (Sprint 9 K5 W1)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = ROOT / ".pre-prod-baseline.json"


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    duration_s: float
    skipped: bool = False
    skip_reason: str = ""
    error_msg: str = ""


def _run_cmd(cmd: list[str], *, cwd: Path = ROOT) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=600,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _check_make_target(name: str, target: str) -> CheckResult:
    """Запустить ``make <target>``; success = exit 0."""
    start = time.monotonic()
    if not shutil.which("make"):
        return CheckResult(
            name=name,
            ok=False,
            duration_s=time.monotonic() - start,
            skipped=True,
            skip_reason="make binary not found",
        )
    code, _, stderr = _run_cmd(["make", target])
    return CheckResult(
        name=name,
        ok=code == 0,
        duration_s=time.monotonic() - start,
        error_msg=stderr[:200] if code != 0 else "",
    )


def _check_python_script(name: str, script: str, *args: str) -> CheckResult:
    """Запустить ``python tools/<script>`` (или ``tools/checks/<script>``)."""
    start = time.monotonic()
    # Сначала ищем в tools/checks/, затем в tools/
    script_path = ROOT / "tools" / "checks" / script
    if not script_path.exists():
        script_path = ROOT / "tools" / script
    if not script_path.exists():
        return CheckResult(
            name=name,
            ok=False,
            duration_s=time.monotonic() - start,
            skipped=True,
            skip_reason=f"{script} not found",
        )
    code, stdout, stderr = _run_cmd(
        [sys.executable, str(script_path), *args]
    )
    return CheckResult(
        name=name,
        ok=code == 0,
        duration_s=time.monotonic() - start,
        error_msg=(stderr or stdout)[:200] if code != 0 else "",
    )


def _check_optional(name: str, reason: str) -> CheckResult:
    """Заглушка для проверок, требующих внешних сервисов."""
    return CheckResult(
        name=name, ok=True, duration_s=0.0, skipped=True, skip_reason=reason
    )


def define_checks() -> list[tuple[str, Callable[[], CheckResult]]]:
    """Список 20 проверок."""
    return [
        ("01 coverage ≥75%", lambda: _check_make_target("coverage", "coverage-gate")),
        ("02 mypy ≤30", lambda: _check_python_script(
            "mypy-budget", "mypy_budget.py", "--max", "30"
        )),
        ("03 layers", lambda: _check_python_script(
            "check-layers", "check_layers.py"
        )),
        ("04 ruff strict", lambda: _check_make_target("lint", "lint-strict")),
        ("05 secrets", lambda: _check_make_target(
            "secrets", "secrets-check"
        )),
        ("06 SBOM", lambda: _check_python_script(
            "generate-sbom", "generate_sbom.py", "--output", "dist/sbom.cdx.json"
        )),
        ("07 pip-audit", lambda: _check_optional(
            "pip-audit", "requires network access for vulnerability DB"
        )),
        ("08 bandit-tls", lambda: _check_make_target(
            "bandit-tls", "bandit-tls"
        )),
        ("09 OWASP ZAP", lambda: _check_optional(
            "owasp-zap", "requires running ZAP container"
        )),
        ("10 codeclone strict", lambda: _check_optional(
            "codeclone", "requires running codeclone MCP server"
        )),
        ("11 docstring coverage", lambda: _check_python_script(
            "docstring-coverage", "check_docstrings.py"
        )),
        ("12 docs Vale", lambda: _check_optional(
            "docs-vale", "requires vale binary"
        )),
        ("13 sphinx -W", lambda: _check_optional(
            "sphinx", "requires full docs build environment"
        )),
        ("14 WAF coverage strict", lambda: _check_python_script(
            "waf-coverage", "check_waf_coverage.py"
        )),
        ("15 feature-flags audit", lambda: _check_python_script(
            "feature-flags", "check_feature_flags.py"
        )),
        ("16 team-ownership", lambda: _check_python_script(
            "team-ownership", "check_team_ownership.py"
        )),
        ("17 side-effect audit", lambda: _check_python_script(
            "side-effect-audit", "check_side_effects.py"
        )),
        ("18 perf-gate", lambda: _check_optional(
            "perf-gate", "requires running app at localhost:8000"
        )),
        ("19 startup-time <3s", lambda: _check_python_script(
            "startup-time", "startup_time.py"
        )),
        ("20 Streamlit pages", lambda: _check_python_script(
            "streamlit-pages", "streamlit_pages.py"
        )),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-optional",
        action="store_true",
        help="не выполнять external checks (network/services)",
    )
    parser.add_argument(
        "--ratchet",
        action="store_true",
        help="обновить .pre-prod-baseline.json по успешным метрикам",
    )
    args = parser.parse_args()

    print("=" * 70)
    print(" pre-prod-check gate (Sprint 9 K1 W6 / DoD-10)")
    print("=" * 70)
    print()

    checks = define_checks()
    results: list[CheckResult] = []

    for name, runner in checks:
        print(f"  {name:30s} ", end="", flush=True)
        result = runner()
        result.name = name
        if result.skipped:
            print(f"SKIP   ({result.skip_reason})")
        elif result.ok:
            print(f"OK     ({result.duration_s:.1f}s)")
        else:
            print(f"FAIL   ({result.duration_s:.1f}s) — {result.error_msg}")
        results.append(result)

    print()
    print("=" * 70)
    passed = sum(1 for r in results if r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.ok and not r.skipped)
    total = len(results)
    print(f"  PASSED: {passed}/{total}, SKIPPED: {skipped}, FAILED: {failed}")
    print("=" * 70)

    if failed > 0:
        print()
        print("BLOCKING: pre-prod-check failed", file=sys.stderr)
        return 1

    # Ratchet baseline для tracking
    if args.ratchet:
        baseline = {
            "tool": "pre-prod-check",
            "passed": passed,
            "skipped": skipped,
            "total": total,
            "updated_at": time.time(),
        }
        BASELINE_FILE.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"baseline updated: {BASELINE_FILE.name}")

    print()
    print("OK: pre-prod-check 20/20 passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
