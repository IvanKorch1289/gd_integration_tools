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

S63 W3: миграция argparse → typer+rich. CLI interface (имена флагов,
exit-коды, формат вывода) preserved для backward compat.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import typer
from rich.console import Console

EXIT_OK = 0
EXIT_THRESHOLD_FAIL = 1
EXIT_ERROR = 2

app = typer.Typer(
    name="perf-gate",
    help="Performance gate — запускает locust-сценарий и валидирует пороги.",
    no_args_is_help=True,
    add_completion=False,
)
_err_console = Console(stderr=True, style="red")
_out_console = Console()


def _is_strict_mode(args: Any) -> bool:
    """Проверить, что perf-gate работает в strict-режиме.

    Strict-режим включается:
        - через --strict CLI флаг;
        - через ENV FEATURE_PERF_GATE_STRICT=true;
        - через feature_flags.perf_gate_strict (default-OFF).

    Args:
        args: объект с атрибутом ``.strict`` (argparse.Namespace, SimpleNamespace,
            или любой duck-typed аналог). Сохранён loose contract для backward
            compat с unit-тестами (test_perf_gate_strict_mode_env).

    Returns:
        bool: True если нарушения должны привести к exit 1.
    """
    import os

    if getattr(args, "strict", False):
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
        _err_console.print(f"WARN: baseline parse error: {exc}")
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


def _run_locust(args: Any) -> tuple[int, str]:
    """Запустить locust в headless-режиме.

    Returns:
        (exit_code, stdout_path_or_stderr).
    """
    csv_prefix = f"/tmp/perf_gate_{int(time.time())}"  # noqa: S108
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
        result = subprocess.run(  # noqa: S603
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


def _check_thresholds(metrics: dict[str, Any], args: Any) -> tuple[bool, list[str]]:
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


@app.callback(invoke_without_command=True)
def main(
    scenario: Path = typer.Option(
        ...,
        "--scenario",
        help="Путь к locustfile (например, tests/perf/locust_baseline.py).",
    ),
    users: int = typer.Option(100, "--users", help="Число concurrent users."),
    spawn_rate: int = typer.Option(
        10, "--spawn-rate", help="Users spawn rate per second."
    ),
    duration: str = typer.Option(
        "60s", "--duration", help="Длительность теста (locust format)."
    ),
    host: str = typer.Option("http://localhost:8000", "--host", help="Target host."),
    rps_floor: float = typer.Option(
        1000.0, "--rps-floor", help="Минимум RPS (failure < threshold)."
    ),
    p95_max_ms: float = typer.Option(
        200.0, "--p95-max-ms", help="Максимум p95-latency, мс."
    ),
    p99_max_ms: float = typer.Option(
        500.0, "--p99-max-ms", help="Максимум p99-latency, мс."
    ),
    report: Path | None = typer.Option(
        None, "--report", help="Путь к JSON-отчёту (auto если не указан)."
    ),
    locust_cmd: str = typer.Option(
        "locust", "--locust-cmd", help="Команда locust (default: 'locust')."
    ),
    baseline: Path | None = typer.Option(
        None,
        "--baseline",
        help=(
            "Sprint 6 K2: путь к tests/perf/baseline.json — "
            "пороги читаются оттуда вместо --rps-floor/--p95-max-ms."
        ),
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Sprint 6 K2: переопределяет feature-flag perf_gate_strict — "
            "exit 1 при нарушении порогов."
        ),
    ),
) -> None:
    """Entry-point: typer callback с теми же флагами что и старый argparse."""
    # Build a SimpleNamespace из typer params, чтобы existing helpers
    # (которые принимают args с .attr доступом) работали без изменений.
    args = SimpleNamespace(
        scenario=scenario,
        users=users,
        spawn_rate=spawn_rate,
        duration=duration,
        host=host,
        rps_floor=rps_floor,
        p95_max_ms=p95_max_ms,
        p99_max_ms=p99_max_ms,
        report=report,
        locust_cmd=locust_cmd,
        baseline=baseline,
        strict=strict,
    )

    if not args.scenario.exists():
        _err_console.print(f"ERROR: scenario file not found: {args.scenario}")
        raise typer.Exit(code=EXIT_ERROR)

    _out_console.print(
        f"[perf-gate] starting locust ({args.users} users, {args.duration})..."
    )
    rc, payload = _run_locust(args)
    if rc != EXIT_OK:
        _err_console.print(f"ERROR: {payload}")
        raise typer.Exit(code=EXIT_ERROR)

    metrics = _parse_locust_csv(payload)
    if "error" in metrics:
        _err_console.print(f"ERROR: {metrics['error']}")
        raise typer.Exit(code=EXIT_ERROR)

    # Sprint 6 K2: baseline-режим переопределяет CLI-пороги.
    if args.baseline is not None:
        baseline_data = _load_baseline(args.baseline)
        if not baseline_data:
            _err_console.print(f"WARN: baseline пустой/невалидный {args.baseline}")
            passed, violations = _check_thresholds(metrics, args)
            thresholds_used: dict[str, Any] = {
                "mode": "fallback-args",
                "rps_floor": args.rps_floor,
                "p95_max_ms": args.p95_max_ms,
            }
        else:
            passed, violations = _check_thresholds_baseline(metrics, baseline_data)
            thresholds_used = {
                "mode": "baseline",
                "baseline_path": str(args.baseline),
                "global": baseline_data.get("global", {}),
            }
    else:
        passed, violations = _check_thresholds(metrics, args)
        thresholds_used = {
            "mode": "args",
            "rps_floor": args.rps_floor,
            "p95_max_ms": args.p95_max_ms,
            "p99_max_ms": args.p99_max_ms,
        }

    is_strict = _is_strict_mode(args)
    report_data = {
        "timestamp": int(time.time()),
        "scenario": str(args.scenario),
        "metrics": metrics,
        "thresholds": thresholds_used,
        "passed": passed,
        "violations": violations,
        "strict": is_strict,
        "feature_flag": "perf_gate_strict",
    }

    report_path = args.report or Path(
        f"tests/perf/reports/perf_{int(time.time())}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False))
    _out_console.print(f"[perf-gate] report → {report_path}")

    if passed:
        _out_console.print("[perf-gate] OK — all thresholds passed")
        raise typer.Exit(code=EXIT_OK)
    if is_strict:
        _err_console.print(f"[perf-gate] FAIL (strict) — violations: {violations}")
        raise typer.Exit(code=EXIT_THRESHOLD_FAIL)
    _err_console.print(
        f"[perf-gate] WARN (warn-only; feature_flag perf_gate_strict=false): {violations}"
    )
    raise typer.Exit(code=EXIT_OK)


if __name__ == "__main__":
    app()
