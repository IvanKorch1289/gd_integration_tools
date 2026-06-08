"""CLI-интеграция HTTP/3-сервера.

Используется ``manage.py http3-serve`` — функция ``run_from_settings``
читает ``settings.app.http3_*``, проверяет наличие ``aioquic`` и
запускает event-loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.backend.entrypoints.http3.config import Http3ServerConfig
from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

__all__ = ("run_from_settings",)


def _ensure_aioquic_installed() -> None:
    try:
        import aioquic  # noqa: F401
    except ImportError as exc:  # pragma: no cover — env-dependent
        raise RuntimeError(
            "HTTP/3 server требует extra ``http3``: "
            "uv sync --extra http3 (или pip install aioquic>=1.1)."
        ) from exc


def run_from_settings() -> None:
    """Запустить HTTP/3-сервер на основе глобального ``settings.app``.

    Импорты ``create_app`` / ``serve_http3`` выполняются только после
    проверки настроек — это позволяет вернуть человекочитаемый
    ``RuntimeError`` без полной инициализации DI/lifespan.
    """
    from src.backend.core.config.settings import settings

    app_settings = settings.app
    if not app_settings.http3_enabled:
        raise RuntimeError("HTTP/3 не активирован: установите APP_HTTP3_ENABLED=true.")
    if not app_settings.http3_certfile or not app_settings.http3_keyfile:
        raise RuntimeError(
            "HTTP/3 требует валидные APP_HTTP3_CERTFILE и APP_HTTP3_KEYFILE."
        )

    _ensure_aioquic_installed()

    config = Http3ServerConfig(
        host=app_settings.host,
        port=app_settings.http3_port,
        certfile=Path(app_settings.http3_certfile),
        keyfile=Path(app_settings.http3_keyfile),
        max_datagram_frame_size=app_settings.http3_max_datagram_frame_size,
        idle_timeout=app_settings.http3_idle_timeout,
    )

    from src.backend.entrypoints.http3.server import serve_http3
    from src.backend.plugins.composition.app_factory import create_app

    app = create_app()
    logger.info(
        "Starting HTTP/3 server on udp://%s:%s (cert=%s)",
        config.host,
        config.port,
        config.certfile,
    )
    asyncio.run(serve_http3(app, config))
