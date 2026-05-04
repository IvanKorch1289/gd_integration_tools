"""Точка входа FastAPI-приложения.

Создаёт ASGI-приложение через app_factory и запускает его выбранным
ASGI-сервером. Поддерживаются два бэкенда:

* uvicorn — предпочтителен для разработки, поддерживает hot-reload;
* granian — предпочтителен для production, Rust-реализация поверх uvloop.

Выбор управляется ``settings.app.server`` (env ``APP_SERVER``) и
``settings.app.workers`` (env ``APP_WORKERS``).
"""

from __future__ import annotations

from fastapi import FastAPI

from src.core.config.settings import settings
from src.plugins.composition.app_factory import create_app

app: FastAPI = create_app()


def _run_uvicorn() -> None:
    """Запуск приложения через uvicorn (dev по умолчанию).

    Wave 7.5: backlog/keep-alive/loop конфигурируются через
    ``settings.app`` (listen_backlog, keep_alive_timeout). uvloop —
    активный event-loop для production-pofилей.
    """
    import uvicorn

    is_dev = settings.app.environment in {"development", "testing"}
    uvicorn_kwargs: dict[str, object] = {
        "app": "src.main:app",
        "host": settings.app.host,
        "port": settings.app.port,
        "log_level": "debug" if settings.app.debug_mode else "info",
        "use_colors": settings.app.environment != "production",
        "limit_concurrency": 1000,
        "timeout_keep_alive": settings.app.keep_alive_timeout,
        "backlog": settings.app.listen_backlog,
        "loop": "uvloop" if not is_dev else "auto",
    }
    if is_dev:
        uvicorn_kwargs["reload"] = settings.app.debug_mode
        uvicorn_kwargs["workers"] = 1
    else:
        uvicorn_kwargs["workers"] = settings.app.workers

    uvicorn.run(**uvicorn_kwargs)


def _run_granian() -> None:
    """Запуск приложения через granian (production по умолчанию).

    Wave 7.5: ALPN-negotiated HTTP/2, настраиваемый backlog, runtime
    mode и threads через ``settings.app``. Loop фиксирован uvloop.
    """
    from granian import Granian
    from granian.constants import HTTPModes, Interfaces, Loops, RuntimeModes
    from granian.log import LogLevels

    http_mode = {
        "auto": HTTPModes.auto,
        "1": HTTPModes.http1,
        "2": HTTPModes.http2,
    }[settings.app.granian_http]

    runtime_mode = {
        "auto": RuntimeModes.auto,
        "mt": RuntimeModes.mt,
        "st": RuntimeModes.st,
    }[settings.app.granian_runtime_mode]

    kwargs: dict[str, object] = {
        "target": "src.main:app",
        "address": settings.app.host,
        "port": settings.app.port,
        "interface": Interfaces.ASGI,
        "workers": settings.app.workers,
        "runtime_threads": settings.app.granian_runtime_threads,
        "runtime_mode": runtime_mode,
        "loop": Loops.uvloop,
        "http": http_mode,
        "backlog": settings.app.listen_backlog,
        "log_level": LogLevels.debug if settings.app.debug_mode else LogLevels.info,
    }
    if settings.app.granian_blocking_threads is not None:
        kwargs["blocking_threads"] = settings.app.granian_blocking_threads

    Granian(**kwargs).serve()


def run() -> None:
    """Запустить ASGI-сервер согласно ``settings.app.server``."""
    match settings.app.server:
        case "granian":
            _run_granian()
        case "uvicorn":
            _run_uvicorn()


if __name__ == "__main__":
    run()
