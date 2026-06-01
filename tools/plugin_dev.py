"""make plugin-dev — поднимает infra-only compose + watch-режим (S10 K5 W4).

DX-8.6: Запускает docker-compose.plugin-dev.yml (postgres + redis +
mock-s3) и затем стартует backend с hot-reload + ``pytest --watch``
для extension'а с указанным NAME.

Запуск:

.. code-block:: bash

    python tools/plugin_dev.py --name my_extension --auto-test
    make plugin-dev NAME=my_extension AUTO_TEST=1

Опции:
* ``--name`` — имя extension (extensions/<name>/) — обязательно;
* ``--compose-up`` — поднять compose (default true);
* ``--auto-test`` — параллельно запустить ``pytest --watch`` на
  ``extensions/<name>/tests/``;
* ``--no-livereload`` — отключить watchdog для frontend.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "ops" / "compose" / "docker-compose.plugin-dev.yml"


def _compose_up() -> int:
    """docker compose up -d с минимальным infra-стеком."""
    if not COMPOSE_FILE.is_file():
        print(f"compose file not found: {COMPOSE_FILE}", file=sys.stderr)
        return 2
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"]
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd)
    return proc.returncode


def _compose_down() -> int:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "down"]
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd).returncode


def _ensure_extension(name: str) -> Path:
    path = ROOT / "extensions" / name
    if not path.is_dir():
        raise FileNotFoundError(f"extensions/{name} не найден")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="plugin-dev launcher (S10 K5 W4)")
    parser.add_argument("--name", required=True, help="extensions/<name>")
    parser.add_argument(
        "--compose-up",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Поднять docker-compose.plugin-dev.yml",
    )
    parser.add_argument(
        "--auto-test",
        action="store_true",
        help="Параллельный pytest --watch на extension/tests/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только напечатать команды (для CI/тестов)",
    )
    args = parser.parse_args(argv)

    try:
        ext_path = _ensure_extension(args.name)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Plugin-dev mode для extension {args.name!r} ({ext_path})")

    if args.compose_up and not args.dry_run:
        rc = _compose_up()
        if rc != 0:
            print(f"compose up failed ({rc})", file=sys.stderr)
            return rc

    env = {**os.environ, "APP_ENV": "dev_light", "EXTENSION_HOT_RELOAD": args.name}
    backend_cmd = [
        sys.executable,
        "manage.py",
        "run",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    test_cmd = [
        sys.executable,
        "-m",
        "pytest",
        f"extensions/{args.name}/tests/",
        "-x",
        "--tb=short",
    ]

    if args.dry_run:
        print("DRY-RUN:")
        print(" backend:", " ".join(backend_cmd))
        if args.auto_test:
            print(" tests:", " ".join(test_cmd))
        return 0

    # Backend как foreground; auto-test — fire-and-forget в фоне.
    test_proc: subprocess.Popen | None = None
    if args.auto_test:
        print("Starting tests in background…")
        test_proc = subprocess.Popen(test_cmd, env=env)

    print("Starting backend (foreground; Ctrl+C — stop)…")
    try:
        return subprocess.run(backend_cmd, env=env).returncode
    finally:
        if test_proc is not None:
            test_proc.terminate()
            test_proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
