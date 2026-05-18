"""Startup-time gate (Sprint 9 K3 W3 + K1 W6).

Измеряет время холодного импорта ключевых модулей и валидирует, что оно
не превышает ``MAX_STARTUP_SECONDS``. Часть pre-prod-check (DoD-10).

Запуск:

.. code-block:: bash

    python tools/checks/startup_time.py
    # exit code 0 — OK
    # exit code 1 — превышен лимит
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import time
from pathlib import Path

MAX_STARTUP_SECONDS = 3.0

# Модули, чьё импорт-время критично для startup'а.
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

    Запускает изолированный python-процесс ``-c "import time, M; …"`` чтобы
    не использовать cached модули родителя.

    Returns:
        Время импорта в секундах. Если процесс failed → возвращает
        :data:`float("inf")`.
    """
    script = (
        "import time, sys\n"
        f"start = time.monotonic()\n"
        f"import {module}\n"
        f"sys.stdout.write(f'{{time.monotonic() - start:.4f}}')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"ERROR importing {module}: {proc.stderr}\n")
        return float("inf")
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return float("inf")


def main() -> int:
    """Run gate.

    Returns:
        Exit code: 0 (OK) или 1 (превышен лимит).
    """
    print(f"Startup-time gate: MAX={MAX_STARTUP_SECONDS}s per module")
    print(f"Modules: {len(CRITICAL_MODULES)}")
    print()

    failed: list[tuple[str, float]] = []
    for module in CRITICAL_MODULES:
        elapsed = measure_import(module)
        status = "OK" if elapsed < MAX_STARTUP_SECONDS else "FAIL"
        print(f"  [{status}] {module}: {elapsed:.3f}s")
        if elapsed >= MAX_STARTUP_SECONDS:
            failed.append((module, elapsed))

    if failed:
        print()
        print(f"FAILED {len(failed)} modules exceed {MAX_STARTUP_SECONDS}s")
        return 1
    print()
    print("OK: all critical modules import within budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
