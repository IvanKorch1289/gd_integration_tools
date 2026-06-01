"""Integration smoke-test V5: двойной POST с одинаковым ``Idempotency-Key``.

Сценарий:
1. POST /test-endpoint c ``Idempotency-Key: smoke-1`` → 201, тело {"n": 1}.
2. POST /test-endpoint c тем же ключом → 200, ``Idempotent-Replayed: true``,
   тело {"n": 1} (response из backend'а).

Backend подменён ``MemoryBackend`` — мы тестируем именно middleware-цепочку
+ wiring через :func:`build_idempotency_backend`, а не Redis-инфраструктуру
(она покрыта unit-тестами ``test_idempotency_redis_backend``).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from idempotency_header_middleware import IdempotencyHeaderMiddleware
from idempotency_header_middleware.backends.memory import MemoryBackend


@pytest.fixture
def app_with_idempotency() -> FastAPI:
    """Минимальное FastAPI-приложение с подключённым idempotency-middleware.

    Не используем :func:`build_idempotency_backend` напрямую — он внутри
    пытается выйти на реальный Redis-DI (см. ``_LazyRedisProxy``), что
    нужно только для prod. Здесь explicitly ``MemoryBackend``.
    """
    app = FastAPI()
    counter = {"n": 0}

    app.add_middleware(IdempotencyHeaderMiddleware, backend=MemoryBackend())

    @app.post("/test-endpoint", status_code=201)
    def endpoint() -> dict[str, int]:
        counter["n"] += 1
        return {"n": counter["n"]}

    return app


def test_double_post_same_key_replays(app_with_idempotency: FastAPI) -> None:
    client = TestClient(app_with_idempotency)
    headers = {"Idempotency-Key": "smoke-1"}

    first = client.post("/test-endpoint", headers=headers)
    second = client.post("/test-endpoint", headers=headers)

    assert first.status_code == 201
    assert first.json() == {"n": 1}
    assert first.headers.get("Idempotent-Replayed") is None

    # Replay: handler не должен вызываться повторно — counter остаётся 1.
    assert second.json() == {"n": 1}
    assert second.headers.get("Idempotent-Replayed") == "true"


def test_different_keys_invoke_handler_independently(
    app_with_idempotency: FastAPI,
) -> None:
    client = TestClient(app_with_idempotency)
    first = client.post("/test-endpoint", headers={"Idempotency-Key": "k1"})
    second = client.post("/test-endpoint", headers={"Idempotency-Key": "k2"})

    assert first.json() == {"n": 1}
    assert second.json() == {"n": 2}


def test_request_without_idempotency_header_passes_through(
    app_with_idempotency: FastAPI,
) -> None:
    client = TestClient(app_with_idempotency)
    first = client.post("/test-endpoint")
    second = client.post("/test-endpoint")
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["n"] != second.json()["n"]
