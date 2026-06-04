"""Unit-tests for EmailSink."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from email.message import EmailMessage
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.interfaces.sink import SinkKind, SinkResult
from src.backend.infrastructure.sinks.email_sink import EmailSink


@pytest.fixture
def fake_aiosmtplib(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Stub aiosmtplib with async send()."""
    fake_mod = types.ModuleType("aiosmtplib")
    fake_mod.send = AsyncMock(return_value=None)
    monkeypatch.setitem(sys.modules, "aiosmtplib", fake_mod)
    return fake_mod


@pytest.mark.asyncio
async def test_kind_is_mail() -> None:
    sink = EmailSink(sink_id="e1", host="smtp.test", from_addr="a@test")
    assert sink.kind == SinkKind.MAIL


@pytest.mark.asyncio
async def test_send_dict_payload_success(fake_aiosmtplib: types.ModuleType) -> None:
    sink = EmailSink(
        sink_id="e1",
        host="smtp.test",
        port=587,
        from_addr="sender@test",
        default_to="default@test",
        default_subject="Hello",
    )
    result = await sink.send({"to": "alice@test", "subject": "Subj", "body": "body"})
    assert result.ok is True
    assert result.details["to"] == "alice@test"
    assert result.details["subject"] == "Subj"
    fake_aiosmtplib.send.assert_awaited_once()
    call_args = fake_aiosmtplib.send.call_args
    msg = call_args[0][0]
    assert isinstance(msg, EmailMessage)
    assert msg["To"] == "alice@test"


@pytest.mark.asyncio
async def test_send_str_payload_success(fake_aiosmtplib: types.ModuleType) -> None:
    sink = EmailSink(
        sink_id="e2",
        host="smtp.test",
        from_addr="sender@test",
        default_to="default@test",
    )
    result = await sink.send("plain text")
    assert result.ok is True
    fake_aiosmtplib.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_html_payload(fake_aiosmtplib: types.ModuleType) -> None:
    sink = EmailSink(
        sink_id="e3", host="smtp.test", from_addr="f@test", default_to="t@test"
    )
    result = await sink.send({"body": "<b>hi</b>", "html": True})
    assert result.ok is True
    msg = fake_aiosmtplib.send.call_args[0][0]
    assert msg.is_multipart()
    html_part = next(p for p in msg.iter_parts() if p.get_content_type() == "text/html")
    assert html_part is not None
    assert html_part.get_payload(decode=True).strip() == b"<b>hi</b>"


@pytest.mark.asyncio
async def test_send_cc_and_bcc(fake_aiosmtplib: types.ModuleType) -> None:
    sink = EmailSink(
        sink_id="e4", host="smtp.test", from_addr="f@test", default_to="t@test"
    )
    result = await sink.send({"cc": ["c1@test", "c2@test"], "bcc": "bc@test"})
    assert result.ok is True
    msg = fake_aiosmtplib.send.call_args[0][0]
    assert msg["Cc"] == "c1@test, c2@test"
    assert msg["Bcc"] == "bc@test"


@pytest.mark.asyncio
async def test_send_missing_to_and_default_to_returns_error() -> None:
    sink = EmailSink(sink_id="e5", host="smtp.test", from_addr="f@test")
    result = await sink.send({"body": "x"})
    assert result.ok is False
    assert "invalid" in result.details["error"]


@pytest.mark.asyncio
async def test_send_missing_from_addr_returns_error() -> None:
    sink = EmailSink(sink_id="e6", host="smtp.test", default_to="t@test")
    result = await sink.send("body")
    assert result.ok is False
    assert "invalid" in result.details["error"]


@pytest.mark.asyncio
async def test_send_invalid_payload_type_returns_error() -> None:
    sink = EmailSink(
        sink_id="e7", host="smtp.test", from_addr="f@test", default_to="t@test"
    )
    result = await sink.send(12345)
    assert result.ok is False
    assert "invalid" in result.details["error"]


@pytest.mark.asyncio
async def test_send_returns_false_when_aiosmtplib_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "aiosmtplib", None)  # type: ignore[arg-type]
    sink = EmailSink(
        sink_id="e8", host="smtp.test", from_addr="f@test", default_to="t@test"
    )
    result = await sink.send("body")
    assert result.ok is False
    assert "aiosmtplib" in result.details["error"]


@pytest.mark.asyncio
async def test_send_handles_smtp_exception(fake_aiosmtplib: types.ModuleType) -> None:
    fake_aiosmtplib.send = AsyncMock(side_effect=ConnectionRefusedError(" refused"))
    sink = EmailSink(
        sink_id="e9", host="smtp.test", from_addr="f@test", default_to="t@test"
    )
    result = await sink.send("body")
    assert result.ok is False
    assert "refused" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true_when_connect_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_mod = types.ModuleType("aiosmtplib")
    fake_client = AsyncMock()
    fake_client.connect = AsyncMock()
    fake_client.quit = AsyncMock()
    fake_mod.SMTP = lambda **_: fake_client
    monkeypatch.setitem(sys.modules, "aiosmtplib", fake_mod)
    sink = EmailSink(sink_id="e10", host="smtp.test", from_addr="f@test")
    assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_false_when_connect_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_mod = types.ModuleType("aiosmtplib")
    fake_client = AsyncMock()
    fake_client.connect = AsyncMock(side_effect=OSError("fail"))
    fake_mod.SMTP = lambda **_: fake_client
    monkeypatch.setitem(sys.modules, "aiosmtplib", fake_mod)
    sink = EmailSink(sink_id="e11", host="smtp.test", from_addr="f@test")
    assert await sink.health() is False


@pytest.mark.asyncio
async def test_health_false_when_aiosmtplib_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "aiosmtplib", None)  # type: ignore[arg-type]
    sink = EmailSink(sink_id="e12", host="smtp.test", from_addr="f@test")
    assert await sink.health() is False
