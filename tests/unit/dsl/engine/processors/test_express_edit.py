"""Tests for src.backend.dsl.engine.processors.express.edit.

T3 coverage sprint cycle 5: тесты для ``ExpressEditProcessor.__init__``
(validation/deps) и ``process()`` (HTTP edit через client).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.express.edit import ExpressEditProcessor


def _make_exchange(properties: dict | None = None) -> tuple[Exchange, dict]:
    """Exchange stub with captured properties setter."""
    captured: dict = {}
    ex = MagicMock(spec=Exchange)
    ex.properties = properties or {}

    def _set_property(key: str, value: object) -> None:
        captured[key] = value

    def _fail(reason: str) -> None:
        captured["__fail__"] = reason

    ex.set_property = _set_property  # type: ignore[attr-defined]
    ex.fail = _fail  # type: ignore[attr-defined]
    return ex, captured


def _ctx() -> ExecutionContext:
    return MagicMock(spec=ExecutionContext)


# ─────────── __init__ / to_spec ───────────


def test_init_defaults() -> None:
    proc = ExpressEditProcessor()
    assert proc._bot == "main_bot"
    assert proc._sync_id_from == "properties.express_sync_id"
    assert proc._body is None
    assert proc._body_from is None
    assert proc._bubble is None
    assert proc._keyboard is None
    assert proc._status is None


def test_init_with_static_body() -> None:
    proc = ExpressEditProcessor(body="static text")
    assert proc._body == "static text"


def test_init_with_body_from() -> None:
    proc = ExpressEditProcessor(body_from="properties.new_text")
    assert proc._body_from == "properties.new_text"


def test_init_with_bubble_keyboard_status() -> None:
    proc = ExpressEditProcessor(
        bubble=[[{"text": "btn"}]],
        keyboard=[[{"text": "kb"}]],
        status="ok",
    )
    assert proc._bubble == [[{"text": "btn"}]]
    assert proc._keyboard == [[{"text": "kb"}]]
    assert proc._status == "ok"


def test_to_spec_minimal() -> None:
    proc = ExpressEditProcessor()
    spec = proc.to_spec()
    assert spec == {
        "express_edit": {"bot": "main_bot", "sync_id_from": "properties.express_sync_id"}
    }


def test_to_spec_full() -> None:
    proc = ExpressEditProcessor(
        bot="custom_bot",
        sync_id_from="body.id",
        body="static",
        body_from="body.txt",
        bubble=[[{"text": "b"}]],
        keyboard=[[{"text": "kb"}]],
        status="ok",
    )
    spec = proc.to_spec()
    assert spec == {
        "express_edit": {
            "bot": "custom_bot",
            "sync_id_from": "body.id",
            "body": "static",
            "body_from": "body.txt",
            "bubble": [[{"text": "b"}]],
            "keyboard": [[{"text": "kb"}]],
            "status": "ok",
        }
    }


# ─────────── process() ───────────


class _FakeClient:
    """Async context manager + edit_message stub."""

    def __init__(self) -> None:
        self.edit_calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def edit_message(self, sync_id: str, **fields: object) -> None:
        self.edit_calls.append((sync_id, fields))


@pytest.mark.asyncio
async def test_process_skips_when_sync_id_missing() -> None:
    """sync_id_from пустой → exchange.fail() → ранний return."""
    proc = ExpressEditProcessor(sync_id_from="body.missing_id")
    ex, captured = _make_exchange(properties={})

    with patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: None,
    ):
        await proc.process(ex, _ctx())

    assert "__fail__" in captured
    assert "sync_id отсутствует" in captured["__fail__"]


@pytest.mark.asyncio
async def test_process_static_body_sends_edit() -> None:
    """Static body → field['body'] = static, no body_from lookup."""
    proc = ExpressEditProcessor(body="new text")
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-123"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: "sync-123",
    ):
        await proc.process(ex, _ctx())

    assert len(fake_client.edit_calls) == 1
    sync_id, fields = fake_client.edit_calls[0]
    assert sync_id == "sync-123"
    assert fields == {"body": "new text"}


@pytest.mark.asyncio
async def test_process_body_from_falls_back_when_static_none() -> None:
    """Если body=None и body_from задан, lookup через resolve_value."""
    proc = ExpressEditProcessor(body_from="body.new_text")
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: "resolved text" if expr == "body.new_text" else "sync-1",
    ):
        await proc.process(ex, _ctx())

    fields = fake_client.edit_calls[0][1]
    assert fields["body"] == "resolved text"


@pytest.mark.asyncio
async def test_process_body_static_takes_priority_over_body_from() -> None:
    """body (static) wins over body_from — if both given, body wins."""
    proc = ExpressEditProcessor(body="static", body_from="body.dynamic")
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: "DYNAMIC_VALUE_SHOULD_NOT_APPEAR",
    ):
        await proc.process(ex, _ctx())

    fields = fake_client.edit_calls[0][1]
    assert fields["body"] == "static"
    # resolve_value for body_from should not have been called (body wins)
    # but resolve_value IS called for sync_id_from


@pytest.mark.asyncio
async def test_process_body_from_none_value_skipped() -> None:
    """body_from resolves to None → 'body' field not added (but other fields kept)."""
    proc = ExpressEditProcessor(body_from="body.maybe", status="ok")
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: None if expr == "body.maybe" else "sync-1",
    ):
        await proc.process(ex, _ctx())

    fields = fake_client.edit_calls[0][1]
    assert "body" not in fields
    assert fields["status"] == "ok"


@pytest.mark.asyncio
async def test_process_bubble_keyboard_status_passed_through() -> None:
    proc = ExpressEditProcessor(
        bubble=[[{"text": "btn1"}]],
        keyboard=[[{"text": "kb"}]],
        status="ok",
    )
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: "sync-1",
    ):
        await proc.process(ex, _ctx())

    fields = fake_client.edit_calls[0][1]
    assert fields == {
        "bubble": [[{"text": "btn1"}]],
        "keyboard": [[{"text": "kb"}]],
        "status": "ok",
    }


@pytest.mark.asyncio
async def test_process_no_fields_skips_edit() -> None:
    """Если ни одно поле не задано → no edit, log debug, return."""
    proc = ExpressEditProcessor()  # no body, no bubble, no keyboard, no status
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: "sync-1",
    ):
        await proc.process(ex, _ctx())

    assert fake_client.edit_calls == []


@pytest.mark.asyncio
async def test_process_client_none_skips() -> None:
    """Если get_express_client вернул None — graceful no-op."""
    proc = ExpressEditProcessor(body="text")
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=None,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: "sync-1",
    ):
        await proc.process(ex, _ctx())

    # No edit attempted, no error raised


@pytest.mark.asyncio
async def test_process_client_exception_records_error() -> None:
    """Если edit_message raises → exchange.set_property('express_edit_error', ...)."""
    proc = ExpressEditProcessor(body="text")
    ex, captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.edit_message = AsyncMock(side_effect=RuntimeError("API failure"))

    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=error_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: "sync-1",
    ):
        await proc.process(ex, _ctx())

    assert captured.get("express_edit_error") == "API failure"


@pytest.mark.asyncio
async def test_process_sync_id_passed_as_string() -> None:
    """sync_id всегда приводится к str перед отправкой в client."""
    proc = ExpressEditProcessor(body="text")
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: 12345 if expr == "properties.express_sync_id" else None,
    ):
        await proc.process(ex, _ctx())

    sync_id_arg = fake_client.edit_calls[0][0]
    assert sync_id_arg == "12345"
    assert isinstance(sync_id_arg, str)


@pytest.mark.asyncio
async def test_process_empty_bubble_clears_buttons() -> None:
    """bubble=[] явно очищает buttons (отличается от bubble=None)."""
    proc = ExpressEditProcessor(bubble=[])
    ex, _captured = _make_exchange(properties={"express_sync_id": "sync-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.edit.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.dsl.engine.processors.express.edit.resolve_value",
        lambda exch, expr: "sync-1",
    ):
        await proc.process(ex, _ctx())

    fields = fake_client.edit_calls[0][1]
    assert fields["bubble"] == []
