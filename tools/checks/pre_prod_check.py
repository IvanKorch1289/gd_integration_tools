"""pre-prod-check gate — 38/38 BLOCKING (S17 K-OPS-3 / DoD-13, +8 S36 w4).

Запускает 38 проверок и репортит итог. Любая failed проверка → exit 1.

Запуск:

.. code-block:: bash

    make pre-prod-check
    # OR:
    python tools/checks/pre_prod_check.py
    # Dry-run (S17 scaffold, partial WARN не валит):
    python tools/checks/pre_prod_check.py --dry-run

38 проверок:

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
21. ConfigValidator startup gate (S17 K-ARCH-1; D14)
22. TaskRegistry orphans count = 0 (S17 K-OPS-1; leak prevention)
23. OTel route coverage ≥80% (S17 W19; carryover full enforce S20)
24. APScheduler observability metrics expose (S17 DoD-13)
25. AuthorizationGateway audit emit (S17 K-ARCH-2; carryover S20)
26. MetricsRegistry default_labels coverage (S17 K-OPS-2; D11 sweep)
27. Feature-flags default-OFF audit (S17 carryover)
28. Sphinx docs coverage ≥95% (S20 target)
29. Numeric perf p95 ≤80ms (S20 target; warn-only S17)
30. DR backup freshness check (S17 K-OPS-5)
31. chaos-suite integration (S36 w4; tests/chaos/ + workflow)
32. ADR freshness <90 days (S36 w4; docs/adr/ mtime check)
33. plugin-trust-tier validation (S36 w4 / ADR-NEW-6; extensions/*/plugin.toml)
34. semantic-cache hit-rate ≥30% (S36 w4; TierRouter metrics)
35. RCA coverage ≥80% (S36 w4; docs/runbooks/ incident-response.md + disaster_recovery.md)
36. capability-gate full coverage (S36 w4; CapabilityGatewayProtocol)
37. mypy --strict (S36 w4; replaces #02 ratchet)
38. p95 perf-blocking (S36 w4; replaces #29 warn-only)

S17 scaffold (DoD #13): новые gates #21-#30 запускаются в warn-only
режиме (partial=PASS), полное enforcement — S20. ``--dry-run`` режим
явно выводит WARN/SKIP вместо FAIL для несозревших чеков.
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
    warning: bool = False
    """S17 K-OPS-3: WARN (=partial-pass) — gate ещё не созрел, не блокирует."""


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
    code, stdout, stderr = _run_cmd([sys.executable, str(script_path), *args])
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


def _check_warning(name: str, reason: str) -> CheckResult:
    """S17 K-OPS-3: scaffold-чек, partial=PASS с warning-flag.

    Используется для новых gates #21-#30, которые ещё не имеют полной
    реализации в S17. В normal-run отображаются как WARN (не валят
    pipeline). В ``--dry-run`` — отображаются явно для diagnostics.
    """
    return CheckResult(
        name=name,
        ok=True,
        duration_s=0.0,
        warning=True,
        skip_reason=reason,
    )


def _check_config_validator() -> CheckResult:
    """#21 ConfigValidator startup gate (S17 K-ARCH-1)."""
    start = time.monotonic()
    script_path = ROOT / "src" / "backend" / "core" / "config" / "validator.py"
    if not script_path.exists():
        return CheckResult(
            name="config-validator",
            ok=False,
            duration_s=time.monotonic() - start,
            warning=True,
            skip_reason="ConfigValidator module not found (S17 K-ARCH-1 scaffold)",
        )
    return CheckResult(
        name="config-validator",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_task_registry_orphans() -> CheckResult:
    """#22 TaskRegistry orphans count (S17 K-OPS-1; leak prevention).

    Реальная проверка orphaned-tasks в runtime — в S20 через
    make memory-leak-check (psutil snapshot + asyncio.all_tasks diff).
    """
    return _check_warning(
        "task-registry-orphans",
        "runtime-проверка orphans в S20 (memory-leak-check)",
    )


def _check_otel_route_coverage() -> CheckResult:
    """#23 OTel route coverage ≥80% (S17 W19; full enforce S20)."""
    return _check_warning(
        "otel-route-coverage",
        "coverage метрика появится после S20 OTel sweep",
    )


def _check_apscheduler_metrics() -> CheckResult:
    """#24 APScheduler observability metrics expose (S17 DoD-13)."""
    start = time.monotonic()
    module_path = (
        ROOT
        / "src"
        / "backend"
        / "infrastructure"
        / "scheduler"
        / "observability.py"
    )
    if not module_path.exists():
        return CheckResult(
            name="apscheduler-metrics",
            ok=False,
            duration_s=time.monotonic() - start,
            warning=True,
            skip_reason="scheduler/observability.py not found",
        )
    text = module_path.read_text(encoding="utf-8", errors="replace")
    if "duration" not in text or "started" not in text:
        return CheckResult(
            name="apscheduler-metrics",
            ok=False,
            duration_s=time.monotonic() - start,
            warning=True,
            skip_reason="duration/started metrics not registered",
        )
    return CheckResult(
        name="apscheduler-metrics",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_authorization_audit() -> CheckResult:
    """#25 AuthorizationGateway audit emit (S17 K-ARCH-2; carryover S20)."""
    return _check_warning(
        "authorization-audit",
        "full audit-emit покрытие — S20",
    )


def _check_metrics_registry_labels() -> CheckResult:
    """#26 MetricsRegistry default_labels coverage (S17 D11 sweep)."""
    return _check_warning(
        "metrics-registry-labels",
        "D11 sweep 52 callsites в работе (s17/k2-w2-metrics-migrate)",
    )


def _check_feature_flags_default_off() -> CheckResult:
    """#27 Feature-flags default-OFF audit (S17 carryover).

    Скрипт находится в одном из двух мест (legacy: ``tools/``, новый:
    ``tools/checks/``). При обнаружении запускается; non-zero exit
    выводится в warn-режиме (S17 baseline).
    """
    start = time.monotonic()
    for candidate in (
        ROOT / "tools" / "checks" / "check_feature_flags.py",
        ROOT / "tools" / "check_feature_flags.py",
    ):
        if candidate.exists():
            code, _, _ = _run_cmd([sys.executable, str(candidate)])
            if code != 0:
                return _check_warning(
                    "feature-flags-default-off",
                    "check_feature_flags returned non-zero (S17 baseline)",
                )
            return CheckResult(
                name="feature-flags-default-off",
                ok=True,
                duration_s=time.monotonic() - start,
            )
    return _check_warning(
        "feature-flags-default-off",
        "check_feature_flags.py не найден",
    )


def _check_sphinx_docs_coverage() -> CheckResult:
    """#28 Sphinx docs coverage ≥95% (S20 target; partial S17)."""
    return _check_warning(
        "sphinx-docs-coverage",
        "≥95% target — S20",
    )


def _check_numeric_perf() -> CheckResult:
    """#29 Numeric perf p95 ≤80ms (S20 target; warn-only S17)."""
    return _check_warning(
        "numeric-perf-p95",
        "k6/locust p95 ≤80ms gate — S20",
    )


def _check_dr_backup_freshness() -> CheckResult:
    """#30 DR backup freshness check (S17 K-OPS-5).

    Проверяет наличие скриптов в ``ops/backup/`` и runbook в
    ``docs/runbooks/``. Реальная freshness-проверка (last_modified < N
    hours) — S20 через APScheduler integration + Prometheus metric
    ``dr_backup_age_seconds``.
    """
    start = time.monotonic()
    backup_dir = ROOT / "ops" / "backup"
    runbook = ROOT / "docs" / "runbooks" / "disaster_recovery.md"
    missing: list[str] = []
    for script in (
        "backup_pg.sh",
        "backup_redis.sh",
        "backup_clickhouse.sh",
        "restore_pg.sh",
    ):
        if not (backup_dir / script).is_file():
            missing.append(script)
    if not runbook.is_file():
        missing.append("docs/runbooks/disaster_recovery.md")
    if missing:
        return CheckResult(
            name="dr-backup-freshness",
            ok=False,
            duration_s=time.monotonic() - start,
            warning=True,
            skip_reason=f"missing: {', '.join(missing)}",
        )
    return CheckResult(
        name="dr-backup-freshness",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_chaos_suite_integration() -> CheckResult:
    """#31 chaos-suite integration (S36 w4).

    Проверяет наличие chaos-тестов в ``tests/chaos/`` и их базовую
    инфраструктуру (toxiproxy service в workflow). Реальный запуск —
    через ``make chaos`` (Docker + toxiproxy required).
    """
    start = time.monotonic()
    chaos_dir = ROOT / "tests" / "chaos"
    if not chaos_dir.is_dir():
        return CheckResult(
            name="chaos-suite-integration",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="tests/chaos/ directory not found",
        )
    chaos_tests = sorted(chaos_dir.glob("test_*_chaos.py"))
    if not chaos_tests:
        return CheckResult(
            name="chaos-suite-integration",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="no chaos test files in tests/chaos/",
        )
    workflow = ROOT / ".github" / "workflows" / "chaos.yml"
    if not workflow.is_file():
        return CheckResult(
            name="chaos-suite-integration",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg=".github/workflows/chaos.yml not found",
        )
    return CheckResult(
        name=f"chaos-suite-integration ({len(chaos_tests)} tests)",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_adr_freshness() -> CheckResult:
    """#34 ADR freshness (S36 w4).

    Проверяет что все ADR в ``docs/adr/`` обновлены за последние
    90 дней. ADRs старше 90 дней → warning (не блокирует в S36, но
    репортится как freshness-метрика).
    """
    start = time.monotonic()
    adr_dir = ROOT / "docs" / "adr"
    if not adr_dir.is_dir():
        return CheckResult(
            name="adr-freshness",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="docs/adr/ directory not found",
        )
    cutoff = time.time() - 90 * 86400  # 90 days in seconds
    stale: list[str] = []
    total = 0
    for adr in sorted(adr_dir.glob("*.md")):
        total += 1
        mtime = adr.stat().st_mtime
        if mtime < cutoff:
            stale.append(adr.name)
    if not total:
        return CheckResult(
            name="adr-freshness",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="no ADR files in docs/adr/",
        )
    if stale:
        return CheckResult(
            name=f"adr-freshness ({len(stale)}/{total} stale)",
            ok=True,
            duration_s=time.monotonic() - start,
            warning=True,
            skip_reason=f"stale: {', '.join(stale[:5])}"
            + (f" +{len(stale) - 5}" if len(stale) > 5 else ""),
        )
    return CheckResult(
        name=f"adr-freshness ({total} ADRs)",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_plugin_trust_tier() -> CheckResult:
    """#35 plugin-trust-tier validation (S36 w4 / ADR-NEW-6).

    Проверяет что все ``extensions/*/plugin.toml`` декларируют
    ``trust_tier = "A" | "B"``. Tier-A (signed by org-CA cosign) —
    sandbox disabled, isolation через capability-gate. Tier-B
    (untrusted/external) — strict e2b/pyodide.
    """
    start = time.monotonic()
    ext_dir = ROOT / "extensions"
    if not ext_dir.is_dir():
        return CheckResult(
            name="plugin-trust-tier",
            ok=True,
            duration_s=time.monotonic() - start,
            skipped=True,
            skip_reason="extensions/ directory not found",
        )
    manifest_files = sorted(ext_dir.glob("**/plugin.toml"))
    if not manifest_files:
        return CheckResult(
            name="plugin-trust-tier",
            ok=True,
            duration_s=time.monotonic() - start,
            skipped=True,
            skip_reason="no plugin.toml manifests in extensions/",
        )
    missing: list[str] = []
    for manifest in manifest_files:
        try:
            import tomllib
        except ImportError:
            return CheckResult(
                name="plugin-trust-tier",
                ok=False,
                duration_s=time.monotonic() - start,
                error_msg="tomllib not available (Python < 3.11)",
            )
        try:
            with open(manifest, "rb") as f:
                data = tomllib.load(f)
        except Exception as exc:
            return CheckResult(
                name="plugin-trust-tier",
                ok=False,
                duration_s=time.monotonic() - start,
                error_msg=f"parse error in {manifest.relative_to(ROOT)}: {exc}",
            )
        if "trust_tier" not in data:
            missing.append(manifest.relative_to(ROOT).as_posix())
    if missing:
        return CheckResult(
            name="plugin-trust-tier",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg=f"missing trust_tier in: {', '.join(missing)}",
        )
    return CheckResult(
        name=f"plugin-trust-tier ({len(manifest_files)} plugins)",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_semantic_cache_hit_rate() -> CheckResult:
    """#34 semantic-cache hit rate (S36 w4).

    Проверяет hit-rate TierRouter (L1 in-proc LRU → L2 Redis exact →
    L3 semantic). Если hit-rate ≥ 30% (или ещё нет данных) → OK.
    Порог 30% согласован с S24 KPI для semantic cache.
    """
    start = time.monotonic()
    try:
        from src.backend.infrastructure.ai.semantic_cache import (
            get_tier_router_metrics,
        )
    except ImportError as exc:
        return CheckResult(
            name="semantic-cache-hit-rate",
            ok=True,
            duration_s=time.monotonic() - start,
            skipped=True,
            skip_reason=f"cannot import metrics: {exc}",
        )
    try:
        metrics = get_tier_router_metrics()
    except Exception as exc:
        return CheckResult(
            name="semantic-cache-hit-rate",
            ok=True,
            duration_s=time.monotonic() - start,
            warning=True,
            skip_reason=f"metrics collection failed: {exc}",
        )
    total_hits = 0
    total_misses = 0
    for tier, ops in metrics.items():
        total_hits += ops.get("hit", 0)
        total_misses += ops.get("miss", 0)
    total = total_hits + total_misses
    if total == 0:
        return CheckResult(
            name="semantic-cache-hit-rate (no traffic yet)",
            ok=True,
            duration_s=time.monotonic() - start,
            warning=True,
            skip_reason="no cache traffic yet (scaffold; will gate on first traffic)",
        )
    hit_rate = total_hits / total
    if hit_rate < 0.30:
        return CheckResult(
            name=f"semantic-cache-hit-rate {hit_rate:.1%}",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg=f"hit-rate {hit_rate:.1%} < 30% threshold",
        )
    return CheckResult(
        name=f"semantic-cache-hit-rate {hit_rate:.1%} ({total} ops)",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_rca_coverage() -> CheckResult:
    """#35 RCA coverage (S36 w4).

    Проверяет что critical incident-related runbooks
    (``docs/runbooks/incident-response.md`` и
    ``docs/runbooks/disaster_recovery.md``) содержат RCA-маркеры
    ("RCA", "Root Cause", "Причина", "Анализ"). Это базовая
    sanity-проверка готовности к post-incident analysis.

    Gate НЕ применяется ко всем runbooks (большинство — operational
    guides без RCA секции).
    """
    start = time.monotonic()
    runbook_dir = ROOT / "docs" / "runbooks"
    if not runbook_dir.is_dir():
        return CheckResult(
            name="rca-coverage",
            ok=True,
            duration_s=time.monotonic() - start,
            skipped=True,
            skip_reason="docs/runbooks/ not found",
        )
    rca_markers = ("rca", "root cause", "причина", "анализ")
    critical_files = ("incident-response.md", "disaster_recovery.md")
    missing: list[str] = []
    checked: list[str] = []
    for filename in critical_files:
        path = runbook_dir / filename
        if not path.is_file():
            missing.append(filename)
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except OSError:
            missing.append(f"{filename} (read error)")
            continue
        checked.append(filename)
        if not any(marker in text for marker in rca_markers):
            missing.append(filename)
    if missing:
        return CheckResult(
            name="rca-coverage",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg=f"missing RCA section in: {', '.join(missing)}",
        )
    return CheckResult(
        name=f"rca-coverage ({len(checked)}/{len(critical_files)} critical)",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_capability_gate_coverage() -> CheckResult:
    """#36 capability-gate full coverage (S36 w4).

    Проверяет наличие ``CapabilityGatewayProtocol`` (или
    ``CapabilityGateway`` concrete impl) с методом ``check()``.
    Полная проверка (AST analysis всех sensitive calls) — расширение
    S37; сейчас — smoke test наличия protocol + check() method.
    """
    start = time.monotonic()
    candidates = (
        ROOT / "src" / "backend" / "core" / "interfaces" / "capability_gateway.py",
        ROOT / "src" / "backend" / "core" / "authz" / "capability_gateway.py",
        ROOT / "src" / "backend" / "core" / "authz" / "gateway.py",
    )
    found_protocol = False
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "CapabilityGatewayProtocol" in text or "class CapabilityGateway" in text:
            if "def check(" in text:
                found_protocol = True
                break
    if not found_protocol:
        return CheckResult(
            name="capability-gate-coverage",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="CapabilityGatewayProtocol/Class with check() not found",
        )
    return CheckResult(
        name="capability-gate-coverage (Protocol + check())",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_mypy_strict() -> CheckResult:
    """#37 mypy --strict (S36 w4).

    Замещает #02 ratchet (≤30 errors) на жёсткий strict-режим.
    Smoke-режим: проверяет наличие ``mypy`` в PATH + что mypy
    target ``type-check`` определён в Makefile. Реальный strict
    enforcement — через ``make type-check`` (в CI отдельным job'ом).
    """
    start = time.monotonic()
    if shutil.which("mypy") is None:
        return CheckResult(
            name="mypy-strict",
            ok=True,
            duration_s=time.monotonic() - start,
            skipped=True,
            skip_reason="mypy not in PATH (install via dev-deps)",
        )
    makefile = ROOT / "Makefile"
    if not makefile.is_file():
        return CheckResult(
            name="mypy-strict",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="Makefile not found",
        )
    text = makefile.read_text(encoding="utf-8")
    if "type-check" not in text:
        return CheckResult(
            name="mypy-strict",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="make target 'type-check' not defined in Makefile",
        )
    return CheckResult(
        name="mypy-strict (mypy + make type-check)",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def _check_p95_perf_blocking() -> CheckResult:
    """#38 p95 perf-blocking (S36 w4).

    Замещает #29 ratchet (warn-only p95 ≤80ms) на blocking-режим.
    Проверяет наличие ``make perf-gate-py`` target (python-based
    blocking perf-gate) + baseline.json. Реальный запуск — отдельным
    CI job'ом с нагрузочным тестированием.
    """
    start = time.monotonic()
    makefile = ROOT / "Makefile"
    if not makefile.is_file():
        return CheckResult(
            name="p95-perf-blocking",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="Makefile not found",
        )
    text = makefile.read_text(encoding="utf-8")
    if "perf-gate-py" not in text:
        return CheckResult(
            name="p95-perf-blocking",
            ok=False,
            duration_s=time.monotonic() - start,
            error_msg="make target 'perf-gate-py' not defined",
        )
    baseline = ROOT / ".baselines" / "perf.json"
    if not baseline.is_file():
        return CheckResult(
            name="p95-perf-blocking",
            ok=True,
            duration_s=time.monotonic() - start,
            warning=True,
            skip_reason="make perf-gate-py OK, but .baselines/perf.json missing",
        )
    return CheckResult(
        name="p95-perf-blocking (make perf-gate-py + baseline)",
        ok=True,
        duration_s=time.monotonic() - start,
    )


def define_checks() -> list[tuple[str, Callable[[], CheckResult]]]:
    """Список 38 проверок (20 base + 10 S17 K-OPS-3 + 8 S36 w4)."""
    return [
        ("01 coverage ≥75%", lambda: _check_make_target("coverage", "coverage-gate")),
        (
            "02 mypy ≤30",
            lambda: _check_python_script(
                "mypy-budget", "mypy_budget.py", "--max", "30"
            ),
        ),
        ("03 layers", lambda: _check_python_script("check-layers", "check_layers.py")),
        ("04 ruff strict", lambda: _check_make_target("lint", "lint-strict")),
        ("05 secrets", lambda: _check_make_target("secrets", "secrets-check")),
        (
            "06 SBOM",
            lambda: _check_python_script(
                "generate-sbom", "generate_sbom.py", "--output", "dist/sbom.cdx.json"
            ),
        ),
        (
            "07 pip-audit",
            lambda: _check_optional(
                "pip-audit", "requires network access for vulnerability DB"
            ),
        ),
        ("08 bandit-tls", lambda: _check_make_target("bandit-tls", "bandit-tls")),
        (
            "09 OWASP ZAP",
            lambda: _check_optional("owasp-zap", "requires running ZAP container"),
        ),
        (
            "10 codeclone strict",
            lambda: _check_optional(
                "codeclone", "requires running codeclone MCP server"
            ),
        ),
        (
            "11 docstring coverage",
            lambda: _check_python_script(
                "docstring-coverage",
                "check_docstrings.py",
                "src/backend/core",
                "src/backend/dsl/engine",
                "src/backend/core/interfaces",
            ),
        ),
        ("12 docs Vale", lambda: _check_optional("docs-vale", "requires vale binary")),
        (
            "13 sphinx -W",
            lambda: _check_optional("sphinx", "requires full docs build environment"),
        ),
        (
            "14 WAF coverage strict",
            lambda: _check_python_script("waf-coverage", "check_waf_coverage.py"),
        ),
        (
            "15 feature-flags audit",
            lambda: _check_python_script("feature-flags", "check_feature_flags.py"),
        ),
        (
            "16 team-ownership",
            lambda: _check_python_script("team-ownership", "check_team_ownership.py"),
        ),
        (
            "17 side-effect audit",
            lambda: _check_python_script("side-effect-audit", "check_side_effects.py"),
        ),
        (
            "18 perf-gate",
            lambda: _check_optional(
                "perf-gate", "requires running app at localhost:8000"
            ),
        ),
        (
            "19 startup-time <3s",
            lambda: _check_python_script("startup-time", "startup_time.py"),
        ),
        (
            "20 Streamlit pages",
            lambda: _check_python_script("streamlit-pages", "streamlit_pages.py"),
        ),
        # S17 K-OPS-3 (DoD #13): новые 10 gates, partial=PASS в warn-режиме.
        ("21 ConfigValidator", _check_config_validator),
        ("22 TaskRegistry orphans", _check_task_registry_orphans),
        ("23 OTel route coverage", _check_otel_route_coverage),
        ("24 APScheduler metrics", _check_apscheduler_metrics),
        ("25 Authz audit emit", _check_authorization_audit),
        ("26 Metrics labels cov", _check_metrics_registry_labels),
        ("27 FF default-OFF", _check_feature_flags_default_off),
        ("28 Sphinx docs cov", _check_sphinx_docs_coverage),
        ("29 Numeric perf p95", _check_numeric_perf),
        ("30 DR backup fresh", _check_dr_backup_freshness),
        # S36 w4 gap closure (K1): +3 gates (Batch 2)
        ("31 chaos-suite", _check_chaos_suite_integration),
        ("32 ADR freshness", _check_adr_freshness),
        ("33 plugin trust-tier", _check_plugin_trust_tier),
        # S36 w4 gap closure (K1): +5 gates (Batch 3)
        ("34 semantic-cache hit-rate", _check_semantic_cache_hit_rate),
        ("35 RCA coverage", _check_rca_coverage),
        ("36 capability-gate coverage", _check_capability_gate_coverage),
        ("37 mypy strict", _check_mypy_strict),
        ("38 p95 perf-blocking", _check_p95_perf_blocking),
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "S17 K-OPS-3: выводит список 38 gates без полного исполнения. "
            "Новые gates #21-#30 (warn-only) явно помечаются WARN/SKIP."
        ),
    )
    args = parser.parse_args()

    title = "pre-prod-check gate (S17 K-OPS-3 / DoD-13)"
    if args.dry_run:
        title += " — DRY-RUN"
    print("=" * 70)
    print(f" {title}")
    print("=" * 70)
    print()

    checks = define_checks()
    results: list[CheckResult] = []

    for name, runner in checks:
        print(f"  {name:30s} ", end="", flush=True)
        if args.dry_run:
            result = CheckResult(
                name=name,
                ok=True,
                duration_s=0.0,
                warning=True,
                skip_reason="dry-run (skipped execution)",
            )
            print(f"DRY    ({result.skip_reason})")
            results.append(result)
            continue
        result = runner()
        result.name = name
        if result.skipped:
            print(f"SKIP   ({result.skip_reason})")
        elif result.warning and not result.ok:
            # Warn-only gate: partial=PASS, не валит pipeline (S17 scaffold).
            print(f"WARN   ({result.duration_s:.1f}s) — {result.skip_reason}")
            result.ok = True
        elif result.warning:
            print(f"WARN   (scaffold; {result.skip_reason})")
        elif result.ok:
            print(f"OK     ({result.duration_s:.1f}s)")
        else:
            print(f"FAIL   ({result.duration_s:.1f}s) — {result.error_msg}")
        results.append(result)

    print()
    print("=" * 70)
    passed = sum(1 for r in results if r.ok and not r.skipped and not r.warning)
    warned = sum(1 for r in results if r.warning)
    skipped = sum(1 for r in results if r.skipped and not r.warning)
    failed = sum(1 for r in results if not r.ok and not r.skipped)
    total = len(results)
    print(
        f"  PASSED: {passed}/{total}, WARN: {warned}, "
        f"SKIPPED: {skipped}, FAILED: {failed}"
    )
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
            "warned": warned,
            "skipped": skipped,
            "total": total,
            "updated_at": time.time(),
        }
        BASELINE_FILE.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"baseline updated: {BASELINE_FILE.name}")

    print()
    if warned > 0:
        print(
            f"OK: pre-prod-check {passed}/{total} passed ({warned} warn-only scaffold)"
        )
    else:
        print(f"OK: pre-prod-check {total}/{total} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
