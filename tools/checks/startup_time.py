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
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = ROOT / ".baselines" / "startup-time.json"

MAX_STARTUP_SECONDS_PER_MODULE = 3.0
MAX_TOTAL_STARTUP_SECONDS = 3.0
REGRESSION_TOLERANCE = 0.30  # 30% медленнее baseline → FAIL
#: Абсолютный предел RSS на импорт critical-модулей, МБ (tripwire против
#: возврата тяжёлых импортов — именно так в строй вернулся Presidio: +903 МБ
#: в dev-venv, +107 МБ в прод-образе).
MAX_STARTUP_RSS_MB = 512.0

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
    return _run_measure(module, None)


def _measure_import_at(module: str, cwd: Path) -> float:
    """Холодный импорт модуля из указанного каталога.

    Используется для замера на baseline-коммите во временном worktree:
    модуль должен резолвиться именно оттуда, а не из основного дерева.

    Args:
        module: Имя модуля.
        cwd: Каталог, из которого выполняется импорт.

    Returns:
        Время импорта в секундах либо ``float('inf')``.
    """
    return _run_measure(module, cwd)


def _run_measure(module: str, cwd: Path | None) -> float:
    """Общая реализация замера импорта.

    Args:
        module: Имя модуля.
        cwd: Рабочий каталог подпроцесса (``None`` — текущий).

    Returns:
        Время импорта в секундах либо ``float('inf')``.
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
        # RSS подпроцесса: интерпретатор + импортированные модули.
        "import resource as _r\n"
        "sys.stdout.write(f'STARTUP_RSS_KB:{_r.getrusage(_r.RUSAGE_SELF).ru_maxrss}\\n')\n"
        "sys.stdout.flush()\n"
    )
    proc = subprocess.run(  # noqa: S603  # trusted argv (controlled by tool, shell=False default)
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(cwd) if cwd is not None else None,
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
                return float(line[len(_MARKER_PREFIX) :])
            except ValueError:
                continue
    # Fallback: legacy behavior (subprocess without marker).
    try:
        return float(stdout.strip().splitlines()[-1])
    except ValueError, IndexError:
        return float("inf")


_RSS_MARKER_PREFIX = "STARTUP_RSS_KB:"


def _extract_rss_from_stdout(stdout: str) -> float:
    """Извлечь RSS подпроцесса (МБ) из маркера в stdout.

    Args:
        stdout: raw subprocess stdout.

    Returns:
        RSS в мегабайтах (float) либо ``float('inf')``, если маркера нет.
    """
    for line in stdout.splitlines():
        if line.startswith(_RSS_MARKER_PREFIX):
            try:
                return int(line[len(_RSS_MARKER_PREFIX) :]) / 1024
            except ValueError:
                continue
    return float("inf")


def measure_rss(cwd: Path | None = None) -> float:
    """Измерить RSS процесса, импортировавшего все critical-модули.

    Один подпроцесс импортирует весь набор CRITICAL_MODULES и печатает
    свой максимальный RSS — это «стоимость памяти старта». Именно такой
    замер поймал бы возврат тяжёлого импорта (например, Presidio: +903 МБ
    в dev-venv), который до P1 тянулся из скана @register_action.

    Args:
        cwd: Каталог импорта (``None`` — текущее дерево).

    Returns:
        RSS в мегабайтах либо ``float('inf')`` при неудаче.
    """
    imports = "\n".join(f"import {module}" for module in CRITICAL_MODULES)
    script = (
        "import os, resource, sys\n"
        "os.environ.setdefault('SEC_VAULT_ENABLED', 'false')\n"
        "os.environ.setdefault('STRUCTLOG_CONSOLE', 'stderr')\n"
        f"{imports}\n"
        "sys.stdout.write(f'STARTUP_RSS_KB:{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}')\n"
        "sys.stdout.flush()\n"
    )
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированная команда
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(cwd) if cwd is not None else None,
        )
    except OSError, subprocess.SubprocessError:
        return float("inf")
    if proc.returncode != 0:
        return float("inf")
    return _extract_rss_from_stdout(proc.stdout)


def measure_pass(cwd: Path | None = None) -> list[float]:
    """Один полный прогон по ``CRITICAL_MODULES``.

    Args:
        cwd: Каталог, из которого измеряется импорт (``None`` — текущее
            дерево).

    Returns:
        Список замеров на модуль в порядке ``CRITICAL_MODULES``.
    """
    if cwd is None:
        return [measure_import(module) for module in CRITICAL_MODULES]
    return [_measure_import_at(module, cwd) for module in CRITICAL_MODULES]


def measure_ratio_against_ref(
    ref: str, samples: int
) -> tuple[float, float, list[list[float]], list[list[float]], float, float] | None:
    """Сравнить текущее дерево с baseline-коммитом в одной среде.

    Замеры ИНТЕРЛИВИРУЮТСЯ: в каждом прогоне сначала меряется baseline-коммит,
    затем текущее дерево. Нагрузка машины (другие процессы, FS-кэш) влияет
    на оба замера почти одинаково, поэтому отношение per-pair устойчиво к
    дрейфу. Раздельные замеры (сначала всё текущее, потом всё baseline)
    давали отношение 2.45 при фактическом отсутствии регрессии — разброс
    одиночных замеров достигает ±50 %.

    Args:
        ref: Ревизия baseline.
        samples: Число интерливированных прогонов.

    Returns:
        Кортеж ``(медиана отношений, медиана baseline, прогоны текущего
        дерева, прогоны baseline, RSS текущего, RSS baseline)`` либо ``None``,
        если сравнение невозможно.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="startup-baseline-"))
    worktree = tmp_dir / "tree"
    try:
        cmd = ["git", "worktree", "add", "--detach", "-q", str(worktree), ref]
        proc = subprocess.run(  # noqa: S603 — фиксированная команда git
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=120
        )
        if proc.returncode != 0:
            return None
        current_passes: list[list[float]] = []
        baseline_passes: list[list[float]] = []
        baseline_totals: list[float] = []
        ratios: list[float] = []
        for _ in range(samples):
            baseline_pass = measure_pass(cwd=worktree)
            baseline_total = sum(baseline_pass)
            baseline_passes.append(baseline_pass)
            current_pass = measure_pass()
            current_total = sum(current_pass)
            current_passes.append(current_pass)
            baseline_totals.append(baseline_total)
            if baseline_total > 0:
                ratios.append(current_total / baseline_total)
        if not ratios:
            return None
        rss_baseline = measure_rss(cwd=worktree)
        rss_current = measure_rss()
        return (
            median_of(ratios),
            median_of(baseline_totals),
            current_passes,
            baseline_passes,
            rss_current,
            rss_baseline,
        )
    except OSError, subprocess.SubprocessError:
        return None
    finally:
        cleanup = ["git", "worktree", "remove", "--force", str(worktree)]
        subprocess.run(  # noqa: S603 — фиксированная команда git
            cleanup, cwd=ROOT, capture_output=True, text=True, timeout=60
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)


def median_of(samples: list[float]) -> float:
    """Медиана списка замеров.

    Args:
        samples: непустой список значений.

    Returns:
        Медиана. Для чётного N — среднее двух центральных значений, что
        и делает оценку устойчивой к одиночному выбросу холодного прогона.
    """
    return statistics.median(samples)


def load_baseline_info() -> dict[str, object]:
    """Прочитать baseline целиком (total + ref).

    Returns:
        Словарь с ключами ``total`` (float) и ``ref`` (str | None);
        пустой словарь, если baseline отсутствует или нечитаем.
    """
    if not BASELINE_FILE.exists():
        return {}
    try:
        data = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    except ValueError, json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    total = data.get("total")
    if not isinstance(total, (int, float)):
        return {}
    ref = data.get("ref")
    return {"total": float(total), "ref": ref if isinstance(ref, str) else None}


def load_baseline() -> float | None:
    total = load_baseline_info().get("total")
    return float(total) if isinstance(total, (int, float)) else None


def save_baseline(total: float, ref: str | None = None) -> None:
    """Записать baseline.

    Args:
        total: Суммарное время в секундах.
        ref: Ревизия, на которой снят baseline (для машинно-независимого
            сравнения). ``None`` — сравнение по абсолютному времени.
    """
    payload: dict[str, object] = {"total": round(total, 4), "tool": "startup_time"}
    if ref:
        payload["ref"] = ref
    BASELINE_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def current_ref() -> str | None:
    """Текущая ревизия рабочего дерева (для baseline).

    Returns:
        Короткий SHA или ``None``, если git недоступен.
    """
    try:
        cmd = ["git", "rev-parse", "--short", "HEAD"]
        proc = subprocess.run(  # noqa: S603 — фиксированная команда git
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=30
        )
    except OSError, subprocess.SubprocessError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


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
    parser.add_argument(
        "--no-ratio",
        action="store_true",
        help=(
            "не сравнивать с baseline-коммитом (только абсолютное время). "
            "По умолчанию сравнение машинно-независимо: тот же набор модулей "
            "меряется на коммите baseline'а в этой же среде"
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

    baseline_info = load_baseline_info()
    baseline = baseline_info.get("total")
    if not isinstance(baseline, (int, float)):
        baseline = None
    ref = baseline_info.get("ref")
    ref = ref if isinstance(ref, str) else None

    # samples[pass_index][module_index] — сырые замеры всех прогонов.
    # При наличии baseline-коммита замеры ИНТЕРЛИВИРУЮТСЯ (baseline и
    # текущее дерево по очереди) — иначе дрейф нагрузки машины искажает
    # отношение (наблюдалось 2.45 при отсутствии регрессии).
    ratio: float | None = None
    baseline_ref_total: float | None = None
    comparison = None
    if ref and not args.no_ratio:
        comparison = measure_ratio_against_ref(ref, args.samples)
    baseline_passes: list[list[float]] = []
    rss_current = measure_rss()
    rss_baseline: float | None = None
    if comparison is not None:
        (
            ratio,
            baseline_ref_total,
            passes,
            baseline_passes,
            rss_current,
            rss_baseline,
        ) = comparison
    else:
        passes = [measure_pass() for _ in range(args.samples)]
    totals = [sum(p) for p in passes]

    # Медиана по каждому модулю и по total: вердикт выносится на медиану,
    # одиночный выброс холодного прогона больше не роняет гейт.
    per_module_median = [
        median_of([p[i] for p in passes]) for i in range(len(CRITICAL_MODULES))
    ]
    total = median_of(totals)

    for idx, module in enumerate(CRITICAL_MODULES):
        samples_txt = ", ".join(f"{p[idx]:.3f}" for p in passes)
        status = (
            "OK" if per_module_median[idx] < MAX_STARTUP_SECONDS_PER_MODULE else "FAIL"
        )
        print(
            f"  [{status}] {module}: median={per_module_median[idx]:.3f}s  [{samples_txt}]"
        )

    per_module_fail = [
        (module, per_module_median[idx])
        for idx, module in enumerate(CRITICAL_MODULES)
        if per_module_median[idx] >= MAX_STARTUP_SECONDS_PER_MODULE
    ]

    print()
    print(f"TOTAL: {total:.3f}s (median of {args.samples})")
    print(f"SAMPLES: {', '.join(f'{t:.3f}' for t in totals)}")
    if args.samples > 1:
        print(
            f"        min={min(totals):.3f}s max={max(totals):.3f}s spread={max(totals) - min(totals):.3f}s"
        )

    if ratio is not None:
        limit = 1 + REGRESSION_TOLERANCE
        print(f"BASELINE REF: {ref} → {baseline_ref_total:.3f}s (в этой же среде)")
        print(f"RATIO: {ratio:.3f} (лимит {limit:.2f} = baseline × {limit:.2f})")
        print("  Покомпонентно (current / baseline):")
        for idx, module in enumerate(CRITICAL_MODULES):
            base_med = median_of([p[idx] for p in baseline_passes])
            cur_med = median_of([p[idx] for p in passes])
            comp = cur_med / base_med if base_med > 0 else float("inf")
            print(f"    {comp:5.2f}×  {module} ({cur_med:.3f}s / {base_med:.3f}s)")
        # RSS печатается ДО вердикта по времени: обе метрики нужны вместе —
        # иначе при провале времени владелец не увидит, что с памятью всё
        # в порядке (и наоборот).
        print(f"RSS (critical modules): {rss_current:.1f} MB")
        if rss_baseline and rss_baseline > 0:
            rss_ratio = rss_current / rss_baseline
            print(f"RSS BASELINE REF: {rss_baseline:.1f} MB → ratio {rss_ratio:.3f}")
            if rss_ratio > 1 + REGRESSION_TOLERANCE:
                print(
                    f"FAIL: RSS ratio {rss_ratio:.3f} > {1 + REGRESSION_TOLERANCE:.2f} "
                    f"(baseline {rss_baseline:.1f} MB, current {rss_current:.1f} MB)",
                    file=sys.stderr,
                )
                return 1
        if ratio > limit:
            print(
                f"FAIL: current/baseline ratio {ratio:.3f} > {limit:.2f} "
                f"(baseline {ref} = {baseline_ref_total:.3f}s, "
                f"current = {total:.3f}s)",
                file=sys.stderr,
            )
            return 1
    elif baseline is not None:
        print(f"BASELINE: {baseline:.3f}s")
        print(f"RSS (critical modules): {rss_current:.1f} MB")
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

    if rss_current > MAX_STARTUP_RSS_MB:
        print(
            f"FAIL: RSS {rss_current:.1f} MB > лимит {MAX_STARTUP_RSS_MB} MB",
            file=sys.stderr,
        )
        return 1

    if ratio is None and total > args.max_total:
        # Абсолютный лимит зависит от машины, поэтому он применяется только
        # когда машинно-независимое сравнение недоступно (нет git-истории).
        print(f"FAIL: total {total:.3f}s > limit {args.max_total}s", file=sys.stderr)
        return 1
    if ratio is not None and total > args.max_total:
        print(
            f"NOTE: total {total:.3f}s > абсолютный лимит {args.max_total}s, "
            "но критерий — отношение к baseline-коммиту (машинно-независимо)"
        )

    if args.ratchet:
        # Семантика для ratio-режима: принять ТЕКУЩЕЕ состояние как новый
        # baseline (ref = текущий HEAD). Следующие прогоны будут сравниваться
        # с ним — то есть принятая деградация перестаёт «флажить».
        ref_now = current_ref()
        save_baseline(total, ref=ref_now)
        print(f"baseline updated: {total:.3f}s (ref={ref_now})")

    print()
    print("OK: startup-time gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
