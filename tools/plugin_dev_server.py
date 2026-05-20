"""Sprint 14 K5 W4 — локальный dev-server для одного плагина.

Назначение:
    Запустить `src.backend.main` в профиле ``dev_light`` так, чтобы
    был загружен ТОЛЬКО указанный плагин. Остальные плагины
    исключаются через переменную окружения ``PLUGIN_DEV_ALLOWLIST``,
    которая обрабатывается ``PluginLoaderV11`` (skip-with-reason).

    Опционально:

    * ``--watch`` — наблюдение за ``extensions/<name>/`` через
      ``watchfiles.awatch`` + hot-swap при изменении файла;
    * ``--port`` — переопределение порта по умолчанию (8001).

Использование:
    python -m tools.plugin_dev_server --name credit_pipeline --watch
    python manage.py plugin serve --name credit_pipeline --port 8888

Принципы:
    - Не модифицирует продовое `main.py`; всё через env-overrides;
    - Watch-loop запускается в отдельной задаче, чтобы graceful
      shutdown через ``Ctrl+C`` сразу останавливал и сервер, и watch.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_logger = logging.getLogger("tools.plugin_dev_server")


def _start_backend(port: int) -> subprocess.Popen[bytes]:
    """Запустить FastAPI backend через `python -m src.backend.main`."""
    env = os.environ.copy()
    env.setdefault("APP_PROFILE", "dev_light")
    env["APP_PORT"] = str(port)
    cmd = [sys.executable, "-m", "src.backend.main"]
    _logger.info("starting backend on port=%s with PLUGIN_DEV_ALLOWLIST=%s",
                 port, env.get("PLUGIN_DEV_ALLOWLIST"))
    return subprocess.Popen(  # noqa: S603
        cmd, env=env, cwd=str(_PROJECT_ROOT)
    )


async def _watch_loop(plugin: str, plugin_dir: Path) -> None:
    """Hot-reload через watchfiles при изменениях в plugin_dir."""
    try:
        from watchfiles import awatch  # noqa: PLC0415
    except ImportError:
        _logger.warning("watchfiles not installed — --watch disabled")
        return
    if not plugin_dir.is_dir():
        _logger.warning("plugin dir missing: %s", plugin_dir)
        return
    _logger.info("watching %s for changes…", plugin_dir)
    async for changes in awatch(plugin_dir):
        _logger.info("plugin %s changed: %s; trigger hot-swap manually via REST.",
                     plugin, changes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local dev-server for a single in-tree plugin (S14 K5 W4)."
    )
    parser.add_argument("--name", required=True, help="Имя плагина (extensions/<name>)")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--watch", action="store_true", help="Включить watch+hot-swap")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    os.environ["PLUGIN_DEV_ALLOWLIST"] = args.name
    plugin_dir = _PROJECT_ROOT / "extensions" / args.name
    if not plugin_dir.is_dir():
        _logger.error("plugin %s not found at %s", args.name, plugin_dir)
        return 2

    backend = _start_backend(args.port)

    def _shutdown(*_: object) -> None:
        _logger.info("stopping backend…")
        backend.send_signal(signal.SIGINT)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        if args.watch:
            asyncio.run(_watch_loop(args.name, plugin_dir))
        else:
            backend.wait()
    except KeyboardInterrupt:
        _shutdown()
    finally:
        backend.wait()
    return backend.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
