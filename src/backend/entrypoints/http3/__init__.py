"""HTTP/3 + WebTransport entrypoint (Sprint 8 opt-in).

Опциональный HTTP/3-сервер на базе ``aioquic``. Запускается параллельно
с основным ASGI-сервером (granian / uvicorn) на отдельном UDP-порту,
работает поверх ASGI-приложения, созданного ``app_factory.create_app``.

Все тяжёлые импорты ``aioquic`` выполняются внутри функций — модуль
импортируется без extra ``http3``. Активация через
``settings.app.http3_enabled = True`` + ``--extra http3``.

Запуск: ``python manage.py http3-serve``.
"""

from __future__ import annotations

from src.backend.entrypoints.http3.config import Http3ServerConfig

__all__ = ("Http3ServerConfig", "serve_http3")


def serve_http3(*args, **kwargs):
    """Запуск HTTP/3 ASGI-сервера (lazy-import).

    Тонкая proxy-функция, которая откладывает import тяжёлой
    ``aioquic``-зависимости до момента вызова. Сигнатура повторяет
    ``src.backend.entrypoints.http3.server.serve_http3``.
    """
    from src.backend.entrypoints.http3.server import serve_http3 as _impl

    return _impl(*args, **kwargs)
