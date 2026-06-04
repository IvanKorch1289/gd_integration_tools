"""Unit tests for express router (BotX command/callback endpoints)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import importlib

mod = importlib.import_module("src.backend.entrypoints.express.router")

print("MOD TYPE:", type(mod), mod)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1")
    return app


@pytest.fixture
def valid_command_payload() -> dict[str, Any]:
    return {
        "bot_id": "bot-1",
        "sync_id": "sync-1",
        "command": {"body": "/profile", "data": {}},
        "from": {"user_huid": "user-1", "username": "Alice"},
        "chat": {"group_chat_id": "chat-1", "chat_type": "group_chat"},
    }


@pytest.fixture
def valid_callback_payload() -> dict[str, Any]:
    return {
        "sync_id": "sync-2",
        "status": "ok",
        "result": {"data": "value"},
    }


# ─── health ──────────────────────────────────────────────────────────────────


def test_health_returns_ok() -> None:
    """GET /health returns status ok."""
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v1/express/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ─── receive_command ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_receive_command_invalid_json() -> None:
    """receive_command returns 400 for invalid JSON."""
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(side_effect=ValueError("bad json"))
    result = await mod.receive_command(mock_request)
    assert result.status_code == 400
    assert result.body == b'{"status":"error","reason":"invalid JSON"}'


@pytest.mark.asyncio
async def test_receive_command_valid(valid_command_payload: dict[str, Any]) -> None:
    """receive_command routes valid payload and returns ok."""
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=valid_command_payload)

    mock_response = {"status": "ok"}

    with patch.object(mod, "_dispatch_to_route", return_value=mock_response):
        result = await mod.receive_command(mock_request)

    assert result.status_code == 200
    data = result.body
    assert b"ok" in data


@pytest.mark.asyncio
async def test_receive_command_no_route(valid_command_payload: dict[str, Any]) -> None:
    """receive_command returns ok with reason no_route when route missing."""
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=valid_command_payload)

    mock_response = {"status": "ok", "reason": "no_route"}

    with patch.object(mod, "_dispatch_to_route", return_value=mock_response):
        result = await mod.receive_command(mock_request)

    assert result.status_code == 200
    assert b"no_route" in result.body


@pytest.mark.asyncio
async def test_receive_command_dispatch_error(valid_command_payload: dict[str, Any]) -> None:
    """receive_command returns error when dispatch fails."""
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=valid_command_payload)

    mock_response = {"status": "error", "reason": "bad input"}

    with patch.object(mod, "_dispatch_to_route", return_value=mock_response):
        result = await mod.receive_command(mock_request)

    assert result.status_code == 200
    assert b"error" in result.body


# ─── receive_callback ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_receive_callback_invalid_json() -> None:
    """receive_callback returns 400 for invalid JSON."""
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(side_effect=ValueError("bad json"))
    result = await mod.receive_callback(mock_request)
    assert result.status_code == 400


@pytest.mark.asyncio
async def test_receive_callback_valid(valid_callback_payload: dict[str, Any]) -> None:
    """receive_callback routes valid payload."""
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value=valid_callback_payload)

    mock_response = {"status": "ok"}

    with patch.object(mod, "_dispatch_to_route", return_value=mock_response):
        result = await mod.receive_callback(mock_request)

    assert result.status_code == 200


# ─── _dispatch_to_route ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_to_route_success() -> None:
    """_dispatch_to_route returns ok when action found and succeeds."""
    mock_bridge = MagicMock()
    mock_bridge.error_code = None
    mock_bridge.success = True

    with patch(
        "src.backend.entrypoints._action_bridge.dispatch_action_or_dsl", return_value=mock_bridge
    ) as mock_dispatch:
        result = await mod._dispatch_to_route(
            "express.command.test", "express.command.default", {"body": "x"}, "sync-1"
        )

    assert result["status"] == "ok"
    mock_dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_to_route_fallback() -> None:
    """_dispatch_to_route tries fallback when primary route not found."""
    primary = MagicMock()
    primary.error_code = "action_not_found"
    primary.success = False

    fallback = MagicMock()
    fallback.error_code = None
    fallback.success = True

    with patch(
        "src.backend.entrypoints._action_bridge.dispatch_action_or_dsl", side_effect=[primary, fallback]
    ) as mock_dispatch:
        result = await mod._dispatch_to_route(
            "express.command.test", "express.command.default", {"body": "x"}, "sync-1"
        )

    assert result["status"] == "ok"
    assert mock_dispatch.call_count == 2


@pytest.mark.asyncio
async def test_dispatch_to_route_no_fallback() -> None:
    """_dispatch_to_route returns no_route when both primary and fallback missing."""
    primary = MagicMock()
    primary.error_code = "action_not_found"
    primary.success = False

    with patch(
        "src.backend.entrypoints._action_bridge.dispatch_action_or_dsl", side_effect=[primary, primary]
    ):
        result = await mod._dispatch_to_route(
            "express.command.test", "express.command.default", {"body": "x"}, "sync-1"
        )

    assert result["status"] == "ok"
    assert result["reason"] == "no_route"


@pytest.mark.asyncio
async def test_dispatch_to_route_no_fallback_id() -> None:
    """_dispatch_to_route returns no_route when fallback_id is None."""
    primary = MagicMock()
    primary.error_code = "action_not_found"
    primary.success = False

    with patch("src.backend.entrypoints._action_bridge.dispatch_action_or_dsl", return_value=primary):
        result = await mod._dispatch_to_route(
            "express.command.test", None, {"body": "x"}, "sync-1"
        )

    assert result["status"] == "ok"
    assert result["reason"] == "no_route"


@pytest.mark.asyncio
async def test_dispatch_to_route_error() -> None:
    """_dispatch_to_route returns error when dispatch fails."""
    mock_bridge = MagicMock()
    mock_bridge.error_code = "dispatch_failed"
    mock_bridge.success = False
    mock_bridge.error = "boom"

    with patch("src.backend.entrypoints._action_bridge.dispatch_action_or_dsl", return_value=mock_bridge):
        result = await mod._dispatch_to_route(
            "express.command.test", None, {"body": "x"}, "sync-1"
        )

    assert result["status"] == "error"
    assert result["reason"] == "boom"


# ─── _log_incoming ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_incoming_appends_message() -> None:
    """_log_incoming appends message to dialog store and pings session."""
    mock_dialog_store = AsyncMock()
    mock_session_store = AsyncMock()

    with patch(
        "src.backend.core.di.providers.get_express_dialog_store_provider", return_value=mock_dialog_store
    ), patch(
        "src.backend.core.di.providers.get_express_session_store_provider", return_value=mock_session_store
    ):
        await mod._log_incoming(
            {
                "bot_id": "bot-1",
                "chat": {"group_chat_id": "chat-1"},
                "from": {"user_huid": "user-1"},
                "command": {"body": "/test"},
            },
            sync_id="sync-1",
        )

    mock_dialog_store.append_message.assert_awaited_once()
    mock_session_store.ping.assert_awaited_once_with("sync-1")


@pytest.mark.asyncio
async def test_log_incoming_graceful_on_error(caplog: pytest.LogCaptureFixture) -> None:
    """_log_incoming silently skips on store error."""
    with patch(
        "src.backend.core.di.providers.get_express_dialog_store_provider", side_effect=RuntimeError("boom")
    ), caplog.at_level("DEBUG"):
        await mod._log_incoming({}, sync_id="sync-1")

    assert "Express incoming log skipped" in caplog.text


# ─── HTTP integration ────────────────────────────────────────────────────────


def test_command_http_400_on_invalid_json() -> None:
    """HTTP POST /command returns 400 for invalid JSON."""
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/api/v1/express/command", data="not-json")
    assert resp.status_code == 400
    assert resp.json()["reason"] == "invalid JSON"


def test_command_http_200(valid_command_payload: dict[str, Any]) -> None:
    """HTTP POST /command returns 200 with valid payload."""
    app = _make_app()
    mock_response = {"status": "ok"}

    with patch.object(mod, "_dispatch_to_route", return_value=mock_response):
        client = TestClient(app)
        resp = client.post("/api/v1/express/command", json=valid_command_payload)

    assert resp.status_code == 200


def test_callback_http_200(valid_callback_payload: dict[str, Any]) -> None:
    """HTTP POST /callback returns 200 with valid payload."""
    app = _make_app()
    mock_response = {"status": "ok"}

    with patch.object(mod, "_dispatch_to_route", return_value=mock_response):
        client = TestClient(app)
        resp = client.post("/api/v1/express/callback", json=valid_callback_payload)

    assert resp.status_code == 200
