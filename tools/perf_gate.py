"""ADR-0055 — Performance gate CLI (Sprint 6 K2 — расширенный baseline.json режим).

Запускает locust-сценарий + анализирует метрики по порогам.

Два режима:

1. **Аргумент-режим** — пороги задаются через --rps-floor/--p95-max-ms/--p99-max-ms.
2. **Baseline-режим** — пороги читаются из ``tests/perf/baseline.json`` (Sprint 6 K2):
   - per-endpoint лимиты;
   - global agregated лимит;
   - feature-flag ``perf_gate_strict`` определяет, блокировать ли при нарушении.

Использование (классическое)::

    python tools/perf_gate.py \\
        --scenario tests/perf/locust_baseline.py \\
        --users 200 \\
        --duration 60s \\
        --rps-floor 1000 \\
        --p95-max-ms 200 \\
        --p99-max-ms 500 \\
        --report tests/perf/reports/perf_$(date +%s).json

Использование (Sprint 6 baseline-режим, warn-only)::

    python tools/perf_gate.py \\
        --scenario tests/perf/locust_baseline.py \\
        --baseline tests/perf/baseline.json \\
        --report dist/perf-report.json

Exit-codes:

* ``0`` — все пороги выполнены ИЛИ feature-flag ``perf_gate_strict=false``;
* ``1`` — нарушен хотя бы один порог при включённом ``perf_gate_strict``;
* ``2`` — error (нет locust / нет сценария / locust-fail).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_THRESHOLD_FAIL = 1
EXIT_ERROR = 2


def _parse_args() -> argparse.Namespace:
    """Разбирает argv в Namespace."""
    parser = argparse.ArgumentParser(
        description="Performance gate — запускает locust-сценарий и валидирует пороги.",
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        required=True,
        help="Путь к locustfile (например, tests/perf/locust_baseline.py).",
    )
    parser.add_argument(
        "--users", type=int, default=100, help="Число concurrent users."
    )
    parser.add_argument(
        "--spawn-rate", type=int, default=10, help="Users spawn rate per second."
    )
    parser.add_argument(
        "--duration", type=str, default="60s", help="Длительность теста (locust format)."
    )
    parser.add_argument("--host", type=str, default="http://localhost:8000", help="Target host.")
    parser.add_argument(
        "--rps-floor", type=float, default=1000.0, help="Минимум RPS (failure < threshold)."
    )
    parser.add_argument(
        "--p95-max-ms", type=float, default=200.0, help="Максимум p95-latency, мс."
    )
    parser.add_argument(
        "--p99-max-ms", type=float, default=500.0, help="Максимум p99-latency, мс."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Путь к JSON-отчёту (auto если не указан).",
    )
    parser.add_argument(
        "--locust-cmd",
        type=str,
        default="locust",
        help="Команда locust (default: 'locust').",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=(
            "Sprint 6 K2: путь к tests/perf/baseline.json — "
            "пороги читаются оттуда вместо --rps-floor/--p95-max-ms."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Sprint 6 K2: переопределяет feature-flag perf_gate_strict — "
            "exit 1 при нарушении порогов."
        ),
    )
    return parser.parse_args()


def _is_strict_mode(args: argparse.Namespace) -> bool:
    """Проверить, что perf-gate работает в strict-режиме.

    Strict-режим включается:
        - через --strict CLI флаг;
        - через ENV FEATURE_PERF_GATE_STRICT=true;
        - через feature_flags.perf_gate_strict (default-OFF).

    Returns:
        bool: True если нарушения должны привести к exit 1.
    """
    import os

    if args.strict:
        return True
    if os.getenv("FEATURE_PERF_GATE_STRICT", "false").lower() in {"1", "true", "yes"}:
        return True
    try:
        from src.backend.core.config.features import feature_flags

        return feature_flags.perf_gate_strict
    except Exception:  # noqa: BLE001
        return False


def _load_baseline(path: Path) -> dict[str, Any]:
    """Прочитать tests/perf/baseline.json в dict.

    Args:
        path: Путь к baseline.json.

    Returns:
        Распарсенный dict; ``{}`` при отсутствии файла.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"WARN: baseline parse error: {exc}", file=sys.stderr)
        return {}


def _check_thresholds_baseline(
    metrics: dict[str, Any], baseline: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Сверить агрегированные метрики с baseline.global.

    Per-endpoint детализация требует CSV per-endpoint (locust ``--csv-full-history``).
    На текущем этапе валидируем только глобальный agregated блок.

    Args:
        metrics: Распарсенные метрики из locust CSV.
        baseline: Содержимое tests/perf/baseline.json.

    Returns:
        (passed, list_of_violations).
    """
    violations: list[str] = []
    global_block = baseline.get("global", {})

    rps_floor = float(global_block.get("rps_floor", 0))
    p95_max = float(global_block.get("p95_ms", 1e9))
    error_rate_max = float(global_block.get("error_rate_max", 1.0))

    rps = float(metrics.get("rps", 0))
    p95 = float(metrics.get("p95_ms", 0))
    fail_rate = float(metrics.get("fail_rate", 0))

    if rps_floor > 0 and rps < rps_floor:
        violations.append(f"RPS {rps:.1f} < floor {rps_floor}")
    if p95 > p95_max:
        violations.append(f"p95 {p95:.1f}ms > max {p95_max}ms")
    if fail_rate > error_rate_max:
        violations.append(f"error_rate {fail_rate:.4f} > max {error_rate_max}")

    return not violations, violations


def _run_locust(args: argparse.Namespace) -> tuple[int, str]:
    """Запустить locust в headless-режиме.

    Returns:
        (exit_code, stdout_path_or_stderr).
    """
    csv_prefix = f"/tmp/perf_gate_{int(time.time())}"
    cmd = [
        args.locust_cmd,
        "-f",
        str(args.scenario),
        "--headless",
        "-u",
        str(args.users),
        "-r",
        str(args.spawn_rate),
        "--run-time",
        args.duration,
        "-H",
        args.host,
        "--csv",
        csv_prefix,
        "--csv-full-history",
        "--only-summary",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, check=False
        )
    except FileNotFoundError:
        return EXIT_ERROR, f"locust not found ({args.locust_cmd})"
    except subprocess.TimeoutExpired:
        return EXIT_ERROR, "locust timeout (>600s)"

    if result.returncode != 0:
        return EXIT_ERROR, f"locust exit {result.returncode}: {result.stderr[:1000]}"
    return EXIT_OK, csv_prefix


def _parse_locust_csv(csv_prefix: str) -> dict[str, Any]:
    """Распарсить ``<prefix>_stats.csv`` в dict с агрегированными метриками."""
    import csv

    stats_path = Path(f"{csv_prefix}_stats.csv")
    if not stats_path.exists():
        return {"error": f"stats csv not found: {stats_path}"}

    aggregated: dict[str, Any] = {}
    with stats_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("Name") == "Aggregated":
                aggregated = {
                    "rps": float(row.get("Requests/s", 0)),
                    "p50_ms": float(row.get("50%", 0)),
                    "p95_ms": float(row.get("95%", 0)),
                    "p99_ms": float(row.get("99%", 0)),
                    "fail_rate": float(row.get("Failure Rate", 0)),
                    "total_requests": int(row.get("Request Count", 0)),
                }
                break
    return aggregated


def _check_thresholds(
    metrics: dict[str, Any], args: argparse.Namespace
) -> tuple[bool, list[str]]:
    """Сверить метрики с порогами.

    Returns:
        (passed, list_of_violations).
    """
    violations: list[str] = []
    rps = float(metrics.get("rps", 0))
    p95 = float(metrics.get("p95_ms", 0))
    p99 = float(metrics.get("p99_ms", 0))

    if rps < args.rps_floor:
        violations.append(f"RPS {rps:.1f} < floor {args.rps_floor}")
    if p95 > args.p95_max_ms:
        violations.append(f"p95 {p95:.1f}ms > max {args.p95_max_ms}ms")
    if p99 > args.p99_max_ms:
        violations.append(f"p99 {p99:.1f}ms > max {args.p99_max_ms}ms")
    return not violations, violations


def main() -> int:
    """Entry-point."""
    args = _parse_args()

    if not args.scenario.exists():
        print(f"ERROR: scenario file not found: {args.scenario}", file=sys.stderr)
        return EXIT_ERROR

    print(f"[perf-gate] starting locust ({args.users} users, {args.duration})...")
    rc, payload = _run_locust(args)
    if rc != EXIT_OK:
        print(f"ERROR: {payload}", file=sys.stderr)
        return EXIT_ERROR

    metrics = _parse_locust_csv(payload)
    if "error" in metrics:
        print(f"ERROR: {metrics['error']}", file=sys.stderr)
        return EXIT_ERROR

    # Sprint 6 K2: baseline-режим переопределяет CLI-пороги.
    if args.baseline is not None:
        baseline = _load_baseline(args.baseline)
        if not baseline:
            print(f"WARN: baseline пустой/невалидный {args.baseline}", file=sys.stderr)
            passed, violations = _check_thresholds(metrics, args)
            thresholds_used: dict[str, Any] = {
                "mode": "fallback-args",
                "rps_floor": args.rps_floor,
                "p95_max_ms": args.p95_max_ms,
            }
        else:
            passed, violations = _check_thresholds_baseline(metrics, baseline)
            thresholds_used = {
                "mode": "baseline",
                "baseline_path": str(args.baseline),
                "global": baseline.get("global", {}),
            }
    else:
        passed, violations = _check_thresholds(metrics, args)
        thresholds_used = {
            "mode": "args",
            "rps_floor": args.rps_floor,
            "p95_max_ms": args.p95_max_ms,
            "p99_max_ms": args.p99_max_ms,
        }

    strict = _is_strict_mode(args)
    report = {
        "timestamp": int(time.time()),
        "scenario": str(args.scenario),
        "metrics": metrics,
        "thresholds": thresholds_used,
        "passed": passed,
        "violations": violations,
        "strict": strict,
        "feature_flag": "perf_gate_strict",
    }

    report_path = args.report or Path(
        f"tests/perf/reports/perf_{int(time.time())}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[perf-gate] report → {report_path}")

    if passed:
        print("[perf-gate] OK — all thresholds passed")
        return EXIT_OK
    if strict:
        print(f"[perf-gate] FAIL (strict) — violations: {violations}", file=sys.stderr)
        return EXIT_THRESHOLD_FAIL
    print(
        f"[perf-gate] WARN (warn-only; feature_flag perf_gate_strict=false): {violations}",
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
