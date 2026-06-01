"""Тесты DSL-шага ``desktop_rpa`` (Wave [wave:s8/k3-rpa-windows-desktop]).

Используют AsyncMock для DesktopRpaClient — реальный pywinauto не нужен.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.desktop_rpa import DesktopRpaProcessor
from src.backend.services.rpa.desktop_rpa_client import DesktopRpaError


def _exchange() -> Exchange[Any]:
    return Exchange(in_message=Message(body={}, headers={}))


def _ctx_with_client(client: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.desktop_rpa_client = client
    return ctx


# ── Validation в __init__ ────────────────────────────────────────────────


def test_init_rejects_unsupported_action() -> None:
    with pytest.raises(ValueError, match="action должен быть"):
        DesktopRpaProcessor(app="app.exe", action="hover")


# ── Happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_click_delegates_to_client_and_writes_property() -> None:
    client = AsyncMock()
    client.execute.return_value = {"ok": True, "action": "click"}
    proc = DesktopRpaProcessor(
        app="C:/Program Files/MyApp/app.exe",
        action="click",
        params={"selector": {"title": "OK"}},
        to="property:rpa.last",
    )
    ex = _exchange()

    await proc.process(ex, context=_ctx_with_client(client))

    assert ex.status != ExchangeStatus.failed
    assert ex.properties["rpa.last"] == {"ok": True, "action": "click"}
    client.execute.assert_awaited_once()
    args = client.execute.await_args.args
    assert args[0] == "click"
    assert args[1]["app"] == "C:/Program Files/MyApp/app.exe"
    assert args[1]["selector"] == {"title": "OK"}


@pytest.mark.asyncio
async def test_type_writes_to_body_field() -> None:
    client = AsyncMock()
    client.execute.return_value = {"ok": True, "action": "type", "chars": 5}
    proc = DesktopRpaProcessor(
        app="app.exe",
        action="type",
        params={"selector": {"auto_id": "username"}, "text": "ivan"},
        to="body.result",
    )
    ex = _exchange()

    await proc.process(ex, context=_ctx_with_client(client))

    assert ex.in_message.body == {"result": {"ok": True, "action": "type", "chars": 5}}


# ── Failure paths ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_client_fails_exchange() -> None:
    proc = DesktopRpaProcessor(app="app.exe", action="click")
    ex = _exchange()
    ctx = MagicMock(spec=[])  # no desktop_rpa_client / app_state

    await proc.process(ex, context=ctx)

    assert ex.status == ExchangeStatus.failed
    assert "DesktopRpaClient" in (ex.error or "")


@pytest.mark.asyncio
async def test_client_error_fails_exchange() -> None:
    client = AsyncMock()
    client.execute.side_effect = DesktopRpaError("sidecar 503")
    proc = DesktopRpaProcessor(app="app.exe", action="click")
    ex = _exchange()

    await proc.process(ex, context=_ctx_with_client(client))

    assert ex.status == ExchangeStatus.failed
    assert "sidecar 503" in (ex.error or "")


# ── Screenshot ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_passes_through_base64() -> None:
    client = AsyncMock()
    client.execute.return_value = {
        "ok": True,
        "format": "png",
        "base64": "iVBORw0KGgo=",
    }
    proc = DesktopRpaProcessor(
        app="app.exe",
        action="screenshot",
        to="property:rpa.shot",
    )
    ex = _exchange()

    await proc.process(ex, context=_ctx_with_client(client))

    assert ex.properties["rpa.shot"]["format"] == "png"
    assert "base64" in ex.properties["rpa.shot"]
