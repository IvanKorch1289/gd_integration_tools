"""Startup-time gate (Sprint 9 K3 W3 + K1 W6, расширен Sprint 10 K2 W3).

Измеряет время холодного импорта ключевых модулей и валидирует, что:

* per-module import не превышает ``MAX_STARTUP_SECONDS_PER_MODULE``;
* total cold-import time не выше ``MAX_TOTAL_STARTUP_SECONDS``;
* total cold-import time не превышает baseline + ``REGRESSION_TOLERANCE``.

Baseline хранится в ``.baselines/startup-time.json``; обновляется
явно через ``--ratchet`` (CI должен это делать при успешном run).

Запуск:

.. code-block:: bash

    python tools/checks/startup_time.py
    # exit 0 — OK; exit 1 — превышен лимит или regression

    python tools/checks/startup_time.py --ratchet
    # обновляет baseline до текущего total time, если стало быстрее
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = ROOT / ".baselines" / "startup-time.json"

MAX_STARTUP_SECONDS_PER_MODULE = 3.0
MAX_TOTAL_STARTUP_SECONDS = 3.0
REGRESSION_TOLERANCE = 0.30  # 30% медленнее baseline → FAIL

CRITICAL_MODULES = (
    "src.backend.core.config.features",
    "src.backend.core.tenancy",
    "src.backend.core.messaging",
    "src.backend.dsl.registry.processor",
    "src.backend.dsl.registry.lazy_processor",
    "src.backend.services.routes.loader",
    "src.backend.infrastructure.messaging.dlq",
)


def measure_import(module: str) -> float:
    """Холодный импорт через subprocess.

    Запускает изолированный python-процесс, чтобы не использовать
    cached модули родителя. Возвращает время импорта в секундах;
    ``float('inf')`` если subprocess failed.
    """
    script = (
        "import time, sys\n"
        "start = time.monotonic()\n"
        f"import {module}\n"
        "sys.stdout.write(f'{time.monotonic() - start:.4f}')\n"
    )
    proc = subprocess.run(  # noqa: S603  # trusted argv (controlled by tool, shell=False default)
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        sys.stderr.write(f"ERROR importing {module}: {proc.stderr}\n")
        return float("inf")
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return float("inf")


def load_baseline() -> float | None:
    if not BASELINE_FILE.exists():
        return None
    try:
        return float(
            json.loads(BASELINE_FILE.read_text(encoding="utf-8")).get("total", 0)
        )
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def save_baseline(total: float) -> None:
    BASELINE_FILE.write_text(
        json.dumps({"total": round(total, 4), "tool": "startup_time"}, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """Run gate."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ratchet",
        action="store_true",
        help="обновить baseline если total стало меньше",
    )
    parser.add_argument(
        "--max-total",
        type=float,
        default=MAX_TOTAL_STARTUP_SECONDS,
        help=f"абсолютный лимит на total time (default {MAX_TOTAL_STARTUP_SECONDS}s)",
    )
    args = parser.parse_args(argv)

    print(f"Startup-time gate: PER-MODULE MAX={MAX_STARTUP_SECONDS_PER_MODULE}s")
    print(f"                    TOTAL MAX={args.max_total}s")
    print(f"                    REGRESSION TOLERANCE={REGRESSION_TOLERANCE * 100:.0f}%")
    print(f"Modules: {len(CRITICAL_MODULES)}")
    print()

    per_module_fail: list[tuple[str, float]] = []
    total: float = 0.0
    for module in CRITICAL_MODULES:
        elapsed = measure_import(module)
        status = "OK" if elapsed < MAX_STARTUP_SECONDS_PER_MODULE else "FAIL"
        print(f"  [{status}] {module}: {elapsed:.3f}s")
        total += elapsed
        if elapsed >= MAX_STARTUP_SECONDS_PER_MODULE:
            per_module_fail.append((module, elapsed))

    print()
    print(f"TOTAL: {total:.3f}s")

    baseline = load_baseline()
    if baseline is not None:
        print(f"BASELINE: {baseline:.3f}s")
        regression_limit = baseline * (1 + REGRESSION_TOLERANCE)
        print(
            f"REGRESSION LIMIT: {regression_limit:.3f}s "
            f"(baseline × {1 + REGRESSION_TOLERANCE})"
        )
        if total > regression_limit:
            print(
                f"FAIL: total {total:.3f}s > regression limit "
                f"{regression_limit:.3f}s (baseline {baseline:.3f}s "
                f"+ {REGRESSION_TOLERANCE * 100:.0f}%)",
                file=sys.stderr,
            )
            return 1

    if per_module_fail:
        print(
            f"FAIL: {len(per_module_fail)} модулей превысили "
            f"{MAX_STARTUP_SECONDS_PER_MODULE}s",
            file=sys.stderr,
        )
        return 1

    if total > args.max_total:
        print(f"FAIL: total {total:.3f}s > limit {args.max_total}s", file=sys.stderr)
        return 1

    if args.ratchet and (baseline is None or total < baseline):
        save_baseline(total)
        print(f"baseline updated: {total:.3f}s")

    print()
    print("OK: startup-time gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
