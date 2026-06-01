"""Sprint 6 K2 — единая точка входа для запуска Granian в production.

Использование::

    uv run python tools/granian_runner.py --app src.main:app
    uv run python tools/granian_runner.py --app src.main:app --port 8000 --dry-run

Все настройки берутся из ``src.backend.core.scaling.granian_tuning.GranianTuning``
(Pydantic-settings), параметры CLI переопределяют конкретные поля.

Feature-flag: ``granian_rsgi_mode_enabled`` (default-OFF). При выключенном
флаге interface принудительно фиксируется на ``asgi``.

ADR-0059 — Granian RSGI production tuning (docs/adr/0059-granian-rsgi-production.md).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys


def _parse_args() -> argparse.Namespace:
    """Разбирает argv в Namespace."""
    parser = argparse.ArgumentParser(
        description=(
            "Sprint 6 K2: запуск Granian с production-tuning из "
            "core/scaling/granian_tuning.py (ADR-0059)."
        ),
    )
    parser.add_argument(
        "--app",
        type=str,
        default="src.main:app",
        help="ASGI/RSGI app в формате module:attr (default: src.main:app).",
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Bind host (default: 0.0.0.0)."
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Bind port (default: 8000)."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Переопределить число воркеров (иначе auto = NCPU).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Вывести CLI-команду и выйти (не запускать Granian).",
    )
    parser.add_argument(
        "--granian-cmd",
        type=str,
        default=None,
        help="Путь к binary granian (default: auto-detect через PATH).",
    )
    return parser.parse_args()


def _resolve_granian_cmd(explicit: str | None) -> str:
    """Найти binary granian в PATH или использовать explicit."""
    if explicit:
        return explicit
    granian = shutil.which("granian")
    if granian is None:
        # fallback: запуск через python -m granian
        return f"{sys.executable} -m granian"
    return granian


def main() -> int:
    """Entry-point."""
    args = _parse_args()

    # lazy-import — не падать при отсутствии pydantic-settings yaml-overlay
    try:
        from src.backend.core.scaling.granian_tuning import granian_tuning
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: не удалось загрузить granian_tuning: {exc}", file=sys.stderr)
        return 2

    granian_cmd = _resolve_granian_cmd(args.granian_cmd)

    # Если workers явно задан — переопределить через ENV (pydantic читает GRANIAN_WORKERS)
    if args.workers is not None:
        os.environ["GRANIAN_WORKERS"] = str(args.workers)

    cmd = granian_tuning.build_cli_command(
        app=args.app,
        host=args.host,
        port=args.port,
        granian_cmd=granian_cmd,
    )

    print(f"[granian-runner] interface={granian_tuning.resolved_interface}")
    print(f"[granian-runner] workers={granian_tuning.resolved_workers}")
    print(f"[granian-runner] blocking_threads={granian_tuning.resolved_blocking_threads}")
    print(f"[granian-runner] loop={granian_tuning.loop}")
    print(f"[granian-runner] command: {' '.join(cmd)}")

    if args.dry_run:
        print("[granian-runner] dry-run: выход без запуска")
        return 0

    # Запуск через subprocess (наследуем stdout/stderr/PID)
    try:
        if granian_cmd.startswith(sys.executable):
            # python -m granian — split на части
            argv = granian_cmd.split() + cmd[1:]
        else:
            argv = cmd
        return subprocess.call(argv)
    except FileNotFoundError:
        print(
            f"ERROR: granian не найден ({granian_cmd}). "
            f"Установите: uv pip install granian",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
