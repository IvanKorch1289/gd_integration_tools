"""Unit-тесты WebDavProcessor — Wave [wave:s5/k3-w3-processor-pack-3]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.webdav_io import WebDavProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_webdav", True)


def test_validates_constructor() -> None:
    with pytest.raises(ValueError, match="mode"):
        WebDavProcessor(url="https://x", mode="invalid", remote_path="/x")
    with pytest.raises(ValueError, match="url"):
        WebDavProcessor(url="", mode="upload", remote_path="/x")


@pytest.mark.asyncio
async def test_fails_when_no_lib(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "webdav4", None)
    monkeypatch.setitem(sys.modules, "webdav4.client", None)
    proc = WebDavProcessor(url="https://dav.test", mode="list", remote_path="/folder")
    ex = _ex()
    await proc.process(ex, AsyncMock())
    assert ex.error is not None and "webdav4" in ex.error.lower()


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_webdav", False)
    proc = WebDavProcessor(url="https://dav.test", mode="list", remote_path="/folder")
    ex = _ex()
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("webdav_status") == "skipped"
