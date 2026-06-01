"""S36 w1 — Smoke tests: WebSocket endpoints.

Tests that /ws and /ws/invocations WebSocket routes are mounted
and accept connections with correct protocol negotiation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.websocket.ws_handler import ws_router
from src.backend.entrypoints.websocket.ws_invocations import ws_invocations_router


def _make_ws_app() -> FastAPI:
    app = FastAPI()
    # Minimal state required by ws_invocations
    app.state.reply_registry = MagicMock()
    app.state.reply_registry.get.return_value = MagicMock()
    app.state.invoker = MagicMock()
    app.include_router(ws_router)
    app.include_router(ws_invocations_router)
    return app


def test_ws_endpoint_accepts_websocket_connection() -> None:
    """WebSocket /ws accepts Upgrade and stays alive (no crash)."""
    client = TestClient(_make_ws_app())
    with client.websocket_connect("/ws") as ws:
        ws.send_text("ping")
        # Smoke: connection accepted, no crash


def test_ws_invocations_accepts_connection() -> None:
    """WebSocket /ws/invocations accepts Upgrade and stays alive."""
    client = TestClient(_make_ws_app())
    with client.websocket_connect("/ws/invocations") as ws:
        ws.send_text("ping")


def test_ws_endpoint_rejects_non_websocket() -> None:
    """GET /ws (without Upgrade) returns 404 or 426 — not a plain HTTP route."""
    client = TestClient(_make_ws_app())
    response = client.get("/ws")
    assert response.status_code in (404, 426, 400)


def test_ws_invocations_rejects_non_websocket() -> None:
    """GET /ws/invocations (without Upgrade) returns 404 or 426."""
    client = TestClient(_make_ws_app())
    response = client.get("/ws/invocations")
    assert response.status_code in (404, 426, 400)
