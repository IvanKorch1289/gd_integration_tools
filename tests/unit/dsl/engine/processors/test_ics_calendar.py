"""Unit-тесты IcsCalendarProcessor — Wave [wave:s5/k3-w3-processor-pack-3]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.ics_calendar import IcsCalendarProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_ics_calendar", True)


@pytest.mark.asyncio
async def test_render_then_parse_roundtrip() -> None:
    pytest.importorskip("icalendar")
    events = [
        {
            "uid": "evt-1@gdit",
            "summary": "Sprint 5 closure",
            "dtstart": "20260514T140000",
            "dtend": "20260514T150000",
        }
    ]
    render = IcsCalendarProcessor(mode="render", source="body", to="body.ics")
    ex1 = _ex(events)
    await render.process(ex1, AsyncMock())
    ics_bytes = ex1.in_message.body["ics"]
    assert isinstance(ics_bytes, bytes)
    assert b"BEGIN:VCALENDAR" in ics_bytes

    parse = IcsCalendarProcessor(mode="parse", source="body.ics", to="body.parsed")
    ex2 = _ex({"ics": ics_bytes})
    await parse.process(ex2, AsyncMock())
    parsed = ex2.in_message.body["parsed"]
    assert len(parsed) == 1
    assert parsed[0]["summary"] == "Sprint 5 closure"


@pytest.mark.asyncio
async def test_render_requires_list() -> None:
    pytest.importorskip("icalendar")
    proc = IcsCalendarProcessor(mode="render", source="body", to="body.ics")
    ex = _ex("not a list")
    await proc.process(ex, AsyncMock())
    assert ex.error is not None and "list" in ex.error.lower()


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_ics_calendar", False)
    proc = IcsCalendarProcessor(mode="parse")
    ex = _ex("")
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("ics_calendar_status") == "skipped"
