"""Unit-тесты :class:`WebhookSignatureMiddleware` (V9).

Покрытие:
* valid signature → 200 + body доходит до handler'а;
* invalid signature → 401;
* expired timestamp (> window) → 401;
* missing X-Webhook-Signature header → 401;
* path вне protected-prefix пропускается без проверки;
* path в protected-prefix без сконфигурированного secret пропускается;
* наиболее специфичный prefix выигрывает при overlap.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.backend.entrypoints.middlewares.webhook_signature import (
    WebhookSignatureMiddleware,
)
from src.backend.infrastructure.security.signatures import sign_payload

WEBHOOK_PATH = "/webhooks/stripe"
SECRET = "supersecret_key_with_enough_entropy_aaaa"


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()

    @app.post(WEBHOOK_PATH)
    async def webhook(request: Request) -> dict:
        body = await request.body()
        return {"received": body.decode(), "length": len(body)}

    @app.get("/public/info")
    def info() -> dict:
        return {"ok": True}

    app.add_middleware(
        WebhookSignatureMiddleware,
        path_prefixes=("/webhooks/",),
        secrets_by_prefix={"/webhooks/stripe": SECRET},
    )
    return app


def test_valid_signature_passes(app: FastAPI) -> None:
    body = b'{"event": "payment.completed"}'
    signature, ts = sign_payload(body, SECRET)
    client = TestClient(app)
    response = client.post(
        WEBHOOK_PATH,
        content=body,
        headers={
            "X-Webhook-Signature": signature,
            "X-Webhook-Timestamp": str(ts),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"received": body.decode(), "length": len(body)}


def test_invalid_signature_returns_401(app: FastAPI) -> None:
    body = b'{"event": "x"}'
    client = TestClient(app)
    response = client.post(
        WEBHOOK_PATH,
        content=body,
        headers={
            "X-Webhook-Signature": "deadbeef",
            "X-Webhook-Timestamp": str(int(time.time())),
        },
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Webhook signature invalid"}


def test_expired_timestamp_returns_401(app: FastAPI) -> None:
    body = b'{"event": "x"}'
    old_ts = int(time.time()) - 3600  # 1 час назад > 300s window
    signature, _ = sign_payload(body, SECRET, timestamp=old_ts)
    client = TestClient(app)
    response = client.post(
        WEBHOOK_PATH,
        content=body,
        headers={"X-Webhook-Signature": signature, "X-Webhook-Timestamp": str(old_ts)},
    )
    assert response.status_code == 401


def test_missing_signature_header_returns_401(app: FastAPI) -> None:
    client = TestClient(app)
    response = client.post(
        WEBHOOK_PATH,
        content=b'{"x": 1}',
        headers={"X-Webhook-Timestamp": str(int(time.time()))},
    )
    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


def test_invalid_timestamp_header_returns_401(app: FastAPI) -> None:
    client = TestClient(app)
    response = client.post(
        WEBHOOK_PATH,
        content=b'{"x": 1}',
        headers={
            "X-Webhook-Signature": "deadbeef",
            "X-Webhook-Timestamp": "not-an-int",
        },
    )
    assert response.status_code == 401
    assert "timestamp" in response.json()["detail"].lower()


def test_unprotected_path_is_not_verified(app: FastAPI) -> None:
    client = TestClient(app)
    response = client.get("/public/info")
    assert response.status_code == 200


def test_protected_prefix_without_secret_passes_through() -> None:
    """Если path в protected, но secret не задан — middleware не блокирует."""
    app = FastAPI()

    @app.post("/webhooks/unconfigured")
    def endpoint(request: Request) -> dict:
        return {"ok": True}

    app.add_middleware(
        WebhookSignatureMiddleware, path_prefixes=("/webhooks/",), secrets_by_prefix={}
    )
    client = TestClient(app)
    response = client.post("/webhooks/unconfigured", json={"x": 1})
    assert response.status_code == 200


def test_most_specific_prefix_wins() -> None:
    """При overlapping prefix'ах используется самый длинный."""
    app = FastAPI()

    @app.post("/webhooks/stripe/payment")
    def endpoint(request: Request) -> dict:
        return {"ok": True}

    secret_specific = "specific-secret-with-enough-entropy-aaaaa"
    app.add_middleware(
        WebhookSignatureMiddleware,
        path_prefixes=("/webhooks/",),
        secrets_by_prefix={
            "/webhooks/": "general-secret-with-enough-entropy-aaaaa",
            "/webhooks/stripe": secret_specific,
        },
    )

    body = b'{"x": 1}'
    sig, ts = sign_payload(body, secret_specific)
    client = TestClient(app)
    response = client.post(
        "/webhooks/stripe/payment",
        content=body,
        headers={"X-Webhook-Signature": sig, "X-Webhook-Timestamp": str(ts)},
    )
    assert response.status_code == 200
