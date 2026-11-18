"""Регресс-тесты: PrometheusMiddleware не создаёт unbounded cardinality.

До фикса (wave 34, infra-аудит) label ``path`` содержал **сырой** URL
(``scope["path"]``) — каждый уникальный entity-id порождал новую
Prometheus-серию (``http_requests_total``, ``http_request_duration_seconds``,
``http_requests_in_progress``). В проде (``monitoring_enabled: true``)
это приводит к росту памяти процесса и OOM Prometheus-сервера.

Покрывает:

* label ``path`` = шаблон маршрута (``/api/v1/orders/{order_id}``), а не сырой URL;
* unmatched-запрос (404) → одна общая серия ``__unmatched__``;
* in-progress gauge имеет только label ``method`` (без path);
* уникальные path-параметры НЕ порождают новые серии.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.application.monitoring import (
    _UNMATCHED_PATH,
    PrometheusMiddleware,
)


class _FakeRoute:
    """Минимальный stand-in для ``starlette.routing.Route``."""

    def __init__(self, path: str) -> None:
        self.path = path


async def _call(app: Any, scope: dict[str, Any]) -> dict[str, Any]:
    """Прогнать scope через middleware; вернуть итоговый scope."""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await PrometheusMiddleware(app)(scope, receive, send)
    return scope


@pytest.fixture
def app() -> Any:
    """ASGI-app, выставляющая ``scope["route"]`` (как это делает Starlette)."""

    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope["route"] = _FakeRoute("/api/v1/orders/{order_id}")
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b""})

    return _app


def _labels_of(metric: Any) -> set[tuple[str, ...]]:
    """Все наборы label-значений, зарегистрированные в метрике."""
    return {tuple(child.labels.values()) for child in metric.collect()[0].samples}  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_path_label_uses_route_template(app: Any) -> None:
    """Label ``path`` = шаблон маршрута, а не сырой URL с entity-id."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/orders/8f14e45f-ceea-467a-9ba2-6f3e9d1c0001",
    }
    await _call(app, scope)

    from src.backend.infrastructure.application.monitoring import _request_count

    paths = {labels[-2] for labels in _labels_of(_request_count) if labels[-2]}
    assert "/api/v1/orders/8f14e45f-ceea-467a-9ba2-6f3e9d1c0001" not in paths
    assert "/api/v1/orders/{order_id}" in paths


@pytest.mark.asyncio
async def test_unique_paths_do_not_create_unique_series(app: Any) -> None:
    """Два запроса с разными id → одна и та же серия метрики."""
    from src.backend.infrastructure.application.monitoring import _request_count

    for entity_id in ("1", "2", "3"):
        scope = {"type": "http", "method": "GET", "path": f"/api/v1/orders/{entity_id}"}
        await _call(app, scope)

    order_series = {
        labels
        for labels in _labels_of(_request_count)
        if "/api/v1/orders/{order_id}" in labels
    }
    assert len(order_series) == 1


@pytest.mark.asyncio
async def test_unmatched_path_uses_single_fallback_label() -> None:
    """Запрос без ``scope["route"]`` → одна серия ``__unmatched__``."""

    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 404})
        await send({"type": "http.response.body", "body": b""})

    for raw in ("/nope/1", "/nope/2"):
        scope = {"type": "http", "method": "GET", "path": raw}
        await _call(_app, scope)

    from src.backend.infrastructure.application.monitoring import _request_count

    assert any(_UNMATCHED_PATH in labels for labels in _labels_of(_request_count))


@pytest.mark.asyncio
async def test_in_progress_gauge_has_no_path_label(app: Any) -> None:
    """In-progress gauge живёт только по ``method`` — без path-label."""
    from src.backend.infrastructure.application.monitoring import _requests_in_progress

    scope = {"type": "http", "method": "GET", "path": "/api/v1/orders/999"}
    await _call(app, scope)

    for child in _requests_in_progress.collect()[0].samples:  # type: ignore[union-attr]
        assert "path" not in child.labels
