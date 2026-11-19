"""Регресс: middleware-цепочка не обрезает стриминговые ответы.

Локализация волны 36: находка предыдущей волны «стриминговый GET-ответ
обрезается до первого чанка полной цепочкой middleware» оказалась
**артефактом измерения**: SSE-эндпоинт ``/events/stream`` по контракту
стримит бесконечно (heartbeat раз в 30 с), а блокирующий клиент на таком
потоке читает первый чанк и виснет — это выглядит как «обрезка».

Здесь фиксируется обратное: конечный стриминговый ответ проходит через
**реальную** цепочку middleware целиком (все чанки доходят до клиента).
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

_CHUNKS = 5

#: Middleware, которые в тестовой цепочке не применяются: они требуют
#: реальной авторизации/сети и к теме теста отношения не имеют.
_DISABLED = frozenset(
    {
        "auth_required",
        "api_key",
        "login_step_up",
        "blocked_routes",
        "ip_restriction",
        "trusted_host",
    }
)


async def _chunks():
    """Конечный генератор: 5 чанков."""
    for index in range(_CHUNKS):
        yield f"chunk-{index}\n".encode()


async def _endpoint(request):
    """Эндпоинт с конечным стриминговым ответом."""
    return StreamingResponse(_chunks(), media_type="text/plain")


def _build_app() -> Starlette:
    """Приложение с реальной цепочкой middleware проекта."""
    from src.backend.entrypoints.middlewares.setup_middlewares import (
        build_default_registry,
    )

    registry = build_default_registry()
    app = Starlette(routes=[Route("/stream", _endpoint)])
    overrides = {name: {"enabled": False} for name in _DISABLED}
    registry.apply_to_app(app, route_overrides=overrides)
    return app


@pytest.mark.unit
class TestStreamingPassthrough:
    """Стриминг проходит через цепочку middleware без обрезки."""

    def test_all_chunks_reach_client(self) -> None:
        """Все чанки конечного стрима доходят до клиента."""
        with TestClient(_build_app()) as client:
            response = client.get("/stream")

        assert response.status_code == 200
        assert response.text.count("chunk-") == _CHUNKS
        assert response.text.startswith("chunk-0\n")

    def test_streaming_response_is_not_buffered_into_error(self) -> None:
        """Стриминг не превращается в 4xx/5xx на стороне middleware."""
        with TestClient(_build_app()) as client:
            response = client.get("/stream")

        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("text/plain")
