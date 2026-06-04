"""Unit-тесты WebSearchProcessor — Wave [wave:s5/k3-w9-web-search-builder]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.web_search import WebSearchProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "web_search_enabled", True)


@pytest.mark.asyncio
async def test_search_with_mocked_service() -> None:
    proc = WebSearchProcessor(
        engine="tavily", query="python 3.14 release", to="body.results"
    )
    ex = _ex({})

    fake_service = AsyncMock()
    fake_service.query = AsyncMock(
        return_value=[{"title": "Python 3.14 Release", "url": "https://x"}]
    )

    with patch(
        "src.backend.infrastructure.clients.external.search_providers.get_web_search_service",
        return_value=fake_service,
    ):
        await proc.process(ex, AsyncMock())

    assert ex.in_message.body["results"][0]["title"] == "Python 3.14 Release"


@pytest.mark.asyncio
async def test_query_from_body_source() -> None:
    proc = WebSearchProcessor(engine="auto", query_source="body.q", to="body.r")
    ex = _ex({"q": "search me"})

    fake_service = AsyncMock()
    fake_service.query = AsyncMock(return_value=[])

    with patch(
        "src.backend.infrastructure.clients.external.search_providers.get_web_search_service",
        return_value=fake_service,
    ):
        await proc.process(ex, AsyncMock())

    fake_service.query.assert_called_once_with(
        "search me", max_results=10, provider=None
    )


@pytest.mark.asyncio
async def test_missing_query_fails() -> None:
    proc = WebSearchProcessor(engine="auto")
    ex = _ex({"x": 1})  # body не строка и нет query/query_source
    await proc.process(ex, AsyncMock())
    assert ex.error is not None and "query" in ex.error


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "web_search_enabled", False)
    proc = WebSearchProcessor(engine="tavily", query="x")
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("web_search_status") == "skipped"
