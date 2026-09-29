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
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = ROOT / ".baselines" / "startup-time.json"

MAX_STARTUP_SECONDS_PER_MODULE = 3.0
MAX_TOTAL_STARTUP_SECONDS = 3.0
REGRESSION_TOLERANCE = 0.30  # 30% медленнее baseline → FAIL

# Число полных прогонов, результат которых сводится к медиане.
# Audit 2026-09-29: одиночный холодный прогон флейкал ~8% (13 замеров
# 1.782–2.263s при лимите 2.145s) — из-за нагрузки на машину и прогрева
# FS-кэша. Медиана снимает флейк по природе; бюджеты НЕ ослаблены.
SAMPLE_COUNT = 3

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

    Fix (cycle 158+ bug): subprocess stdout был загрязнён Vault
    structlog output (hvac missing → repeated error logging при cold
    import config loader). ``float(stdout.strip())`` падал с
    ValueError → ``inf`` для всех 7 critical modules. Новый подход:

    1. В subprocess: отключаем Vault source через env var +
       перенаправляем structlog в stderr.
    2. Marker-based extraction: subprocess prints
       ``STARTUP_TIME_MARKER:<float>`` на last line, parent parses.
    3. ``-X importtime`` НЕ используем — overhead parsingа в разы больше
       самого import time и собьёт baseline.
    """
    script = (
        "import time, sys, os\n"
        # Disable Vault env-flag + suppress structlog (writes to stdout
        # через ConsoleRenderer).
        "os.environ.setdefault('SEC_VAULT_ENABLED', 'false')\n"
        "os.environ.setdefault('STRUCTLOG_CONSOLE', 'stderr')\n"
        "start = time.monotonic()\n"
        f"import {module}\n"
        "elapsed = time.monotonic() - start\n"
        # Marker-based output to avoid stdout pollution from structlog/etc.
        "sys.stdout.write(f'STARTUP_TIME_MARKER:{elapsed:.4f}\\n')\n"
        "sys.stdout.flush()\n"
    )
    proc = subprocess.run(  # noqa: S603  # trusted argv (controlled by tool, shell=False default)
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        sys.stderr.write(f"ERROR importing {module}: {proc.stderr}\n")
        return float("inf")
    return _extract_elapsed_from_stdout(proc.stdout)


# Marker prefix константа — single source of truth.
_MARKER_PREFIX = "STARTUP_TIME_MARKER:"


def _extract_elapsed_from_stdout(stdout: str) -> float:
    """Извлекает elapsed time из subprocess stdout.

    Strategy (cycle 158+ measurement fix):
    1. Primary: marker-based extraction — search for ``STARTUP_TIME_MARKER:<float>``
       в stdout lines. Устойчив к stdout pollution (structlog, Vault logger, etc.).
    2. Fallback: legacy behavior — ``float(stdout.strip().splitlines()[-1])``.
    3. Failure: ``float('inf')`` если ничего parseable.

    Extracted from ``measure_import`` to make it testable in isolation
    (per v4 §10 P1: evidence требует testable surface).

    Args:
        stdout: raw subprocess stdout.

    Returns:
        Elapsed time в секундах (float), или ``float('inf')`` если can't parse.
    """
    for line in stdout.splitlines():
        if line.startswith(_MARKER_PREFIX):
            try:
                return float(line[len(_MARKER_PREFIX):])
            except ValueError:
                continue
    # Fallback: legacy behavior (subprocess without marker).
    try:
        return float(stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return float("inf")


def measure_pass() -> list[float]:
    """Один полный прогон по ``CRITICAL_MODULES``.

    Returns:
        Список замеров на модуль в порядке ``CRITICAL_MODULES``.
    """
    return [measure_import(module) for module in CRITICAL_MODULES]


def median_of(samples: list[float]) -> float:
    """Медиана списка замеров.

    Args:
        samples: непустой список значений.

    Returns:
        Медиана. Для чётного N — среднее двух центральных значений, что
        и делает оценку устойчивой к одиночному выбросу холодного прогона.
    """
    return statistics.median(samples)


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
    parser.add_argument(
        "--samples",
        type=int,
        default=SAMPLE_COUNT,
        help=(
            f"число прогонов, сводимых к медиане (default {SAMPLE_COUNT}). "
            "1 = старое поведение (одиночный холодный замер)"
        ),
    )
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples должен быть >= 1")

    print(f"Startup-time gate: PER-MODULE MAX={MAX_STARTUP_SECONDS_PER_MODULE}s")
    print(f"                    TOTAL MAX={args.max_total}s")
    print(f"                    REGRESSION TOLERANCE={REGRESSION_TOLERANCE * 100:.0f}%")
    print(f"                    SAMPLES={args.samples} (judged on median)")
    print(f"Modules: {len(CRITICAL_MODULES)}")
    print()

    # samples[pass_index][module_index] — сырые замеры всех прогонов.
    passes = [measure_pass() for _ in range(args.samples)]
    totals = [sum(p) for p in passes]

    # Медиана по каждому модулю и по total: вердикт выносится на медиану,
    # одиночный выброс холодного прогона больше не роняет гейт.
    per_module_median = [median_of([p[i] for p in passes]) for i in range(len(CRITICAL_MODULES))]
    total = median_of(totals)

    for idx, module in enumerate(CRITICAL_MODULES):
        samples_txt = ", ".join(f"{p[idx]:.3f}" for p in passes)
        status = "OK" if per_module_median[idx] < MAX_STARTUP_SECONDS_PER_MODULE else "FAIL"
        print(f"  [{status}] {module}: median={per_module_median[idx]:.3f}s  [{samples_txt}]")

    per_module_fail = [
        (module, per_module_median[idx])
        for idx, module in enumerate(CRITICAL_MODULES)
        if per_module_median[idx] >= MAX_STARTUP_SECONDS_PER_MODULE
    ]

    print()
    print(f"TOTAL: {total:.3f}s (median of {args.samples})")
    print(f"SAMPLES: {', '.join(f'{t:.3f}' for t in totals)}")
    if args.samples > 1:
        print(f"        min={min(totals):.3f}s max={max(totals):.3f}s spread={max(totals) - min(totals):.3f}s")

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
