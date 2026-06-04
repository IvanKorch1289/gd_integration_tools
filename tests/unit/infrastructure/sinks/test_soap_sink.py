"""Unit-tests for SoapSink."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.soap_sink import SoapSink, _summarize


@pytest.fixture
def fake_zeep(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Stub zeep module."""
    fake_mod = types.ModuleType("zeep")
    fake_transport_mod = types.ModuleType("zeep.transports")
    fake_mod.transports = fake_transport_mod
    fake_mod.Client = MagicMock
    fake_transport_mod.Transport = MagicMock
    monkeypatch.setitem(sys.modules, "zeep", fake_mod)
    monkeypatch.setitem(sys.modules, "zeep.transports", fake_transport_mod)
    return fake_mod


@pytest.mark.asyncio
async def test_kind_is_soap() -> None:
    sink = SoapSink(sink_id="s1", wsdl_url="http://test/wsdl", operation="op")
    assert sink.kind == SinkKind.SOAP


@pytest.mark.asyncio
async def test_send_dict_payload(fake_zeep: types.ModuleType) -> None:
    fake_service = MagicMock()
    fake_service.op = MagicMock(return_value={"result": 42})
    fake_client = MagicMock()
    fake_client.service = fake_service
    fake_zeep.Client = lambda *a, **k: fake_client  # type: ignore[misc]

    sink = SoapSink(sink_id="s1", wsdl_url="http://test/wsdl", operation="op")
    result = await sink.send({"a": 1})
    assert result.ok is True
    assert result.details["operation"] == "op"
    fake_service.op.assert_called_once_with(a=1)


@pytest.mark.asyncio
async def test_send_non_dict_payload(fake_zeep: types.ModuleType) -> None:
    fake_service = MagicMock()
    fake_service.op = MagicMock(return_value="ok")
    fake_client = MagicMock()
    fake_client.service = fake_service
    fake_zeep.Client = lambda *a, **k: fake_client  # type: ignore[misc]

    sink = SoapSink(sink_id="s2", wsdl_url="http://test/wsdl", operation="op")
    result = await sink.send("raw")
    assert result.ok is True
    fake_service.op.assert_called_once_with(body="raw")


@pytest.mark.asyncio
async def test_send_with_service_and_port(fake_zeep: types.ModuleType) -> None:
    fake_bound = MagicMock()
    fake_bound.doIt = MagicMock(return_value="ok")
    fake_client = MagicMock()
    fake_client.bind = MagicMock(return_value=fake_bound)
    fake_zeep.Client = lambda *a, **k: fake_client  # type: ignore[misc]

    sink = SoapSink(
        sink_id="s3",
        wsdl_url="http://test/wsdl",
        operation="doIt",
        service_name="Svc",
        port_name="Port",
    )
    result = await sink.send({})
    assert result.ok is True
    fake_client.bind.assert_called_once_with("Svc", "Port")


@pytest.mark.asyncio
async def test_send_returns_false_when_zeep_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "zeep", None)  # type: ignore[arg-type]
    sink = SoapSink(sink_id="s4", wsdl_url="http://test/wsdl", operation="op")
    result = await sink.send({})
    assert result.ok is False
    assert "zeep" in result.details["error"]


@pytest.mark.asyncio
async def test_send_handles_invoke_exception(fake_zeep: types.ModuleType) -> None:
    fake_service = MagicMock()
    fake_service.op = MagicMock(side_effect=RuntimeError("soap fault"))
    fake_client = MagicMock()
    fake_client.service = fake_service
    fake_zeep.Client = lambda *a, **k: fake_client  # type: ignore[misc]

    sink = SoapSink(sink_id="s5", wsdl_url="http://test/wsdl", operation="op")
    result = await sink.send({})
    assert result.ok is False
    assert "soap fault" in result.details["error"]


@pytest.mark.asyncio
async def test_send_handles_client_init_exception(fake_zeep: types.ModuleType) -> None:
    fake_zeep.Client = MagicMock(side_effect=OSError("wsdl fail"))  # type: ignore[misc]
    sink = SoapSink(sink_id="s6", wsdl_url="http://test/wsdl", operation="op")
    result = await sink.send({})
    assert result.ok is False
    assert "wsdl fail" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true(fake_zeep: types.ModuleType) -> None:
    fake_client = MagicMock()
    fake_zeep.Client = lambda *a, **k: fake_client  # type: ignore[misc]
    sink = SoapSink(sink_id="s7", wsdl_url="http://test/wsdl", operation="op")
    assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_false_when_zeep_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "zeep", None)  # type: ignore[arg-type]
    sink = SoapSink(sink_id="s8", wsdl_url="http://test/wsdl", operation="op")
    assert await sink.health() is False


@pytest.mark.asyncio
async def test_health_false_on_exception(fake_zeep: types.ModuleType) -> None:
    fake_zeep.Client = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[misc]
    sink = SoapSink(sink_id="s9", wsdl_url="http://test/wsdl", operation="op")
    assert await sink.health() is False


def test_get_client_caches_instance(fake_zeep: types.ModuleType) -> None:
    fake_client = MagicMock()
    fake_zeep.Client = MagicMock(return_value=fake_client)  # type: ignore[misc]
    sink = SoapSink(sink_id="s10", wsdl_url="http://test/wsdl", operation="op")
    c1 = sink._get_client()
    c2 = sink._get_client()
    assert c1 is c2
    fake_zeep.Client.assert_called_once()


def test_summarize_short() -> None:
    assert _summarize("hello") == "'hello'"


def test_summarize_long() -> None:
    long_str = "x" * 300
    result = _summarize(long_str)
    assert result.endswith("...")
    assert len(result) == 256
