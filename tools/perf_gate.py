"""ADR-0055 — Performance gate CLI.

Запускает locust-сценарий + анализирует метрики по порогам:

* ``rps_floor`` — минимум RPS на baseline endpoint;
* ``p95_max_ms`` — максимум p95-latency;
* ``p99_max_ms`` — максимум p99-latency.

Использование::

    python tools/perf_gate.py \\
        --scenario tests/perf/locust_baseline.py \\
        --users 100 \\
        --duration 60s \\
        --rps-floor 1000 \\
        --p95-max-ms 200 \\
        --p99-max-ms 500 \\
        --report tests/perf/reports/perf_$(date +%s).json

Exit-codes:

* ``0`` — все пороги выполнены;
* ``1`` — нарушен хотя бы один порог;
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
    return parser.parse_args()


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

    passed, violations = _check_thresholds(metrics, args)

    report = {
        "timestamp": int(time.time()),
        "scenario": str(args.scenario),
        "metrics": metrics,
        "thresholds": {
            "rps_floor": args.rps_floor,
            "p95_max_ms": args.p95_max_ms,
            "p99_max_ms": args.p99_max_ms,
        },
        "passed": passed,
        "violations": violations,
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
    print(f"[perf-gate] FAIL — violations: {violations}", file=sys.stderr)
    return EXIT_THRESHOLD_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
