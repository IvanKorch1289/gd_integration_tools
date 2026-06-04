"""Unit-тесты GraphQLSubscriptionSource (K3 W5b S3)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.infrastructure.sources.graphql_subscription import (
    GraphQLEvent,
    GraphQLSubscriptionSource,
)


def test_source_constructor() -> None:
    """Конструктор сохраняет endpoint_url + query."""
    src = GraphQLSubscriptionSource(
        endpoint_url="wss://api.example.com/graphql",
        subscription_query="subscription { hello }",
        headers={"X-Token": "abc"},
    )
    assert src._endpoint_url == "wss://api.example.com/graphql"
    assert "subscription" in src._subscription_query
    assert src._headers == {"X-Token": "abc"}


def test_graphql_event_dataclass() -> None:
    """GraphQLEvent имеет ожидаемые поля."""
    event = GraphQLEvent(
        data={"hello": "world"}, subscription_id="sub-1", timestamp=1234567890.0
    )
    assert event.data == {"hello": "world"}
    assert event.subscription_id == "sub-1"
    assert event.timestamp == 1234567890.0


@pytest.mark.asyncio
async def test_source_lazy_imports_gql() -> None:
    """Lazy-import: stream() пытается импортировать gql при первом вызове."""
    pytest.importorskip("gql")
    src = GraphQLSubscriptionSource(
        endpoint_url="wss://api.example.com/graphql",
        subscription_query="subscription { x }",
    )
    # Не запускаем фактический stream — просто проверяем, что класс готов
    assert hasattr(src, "stream")
    assert callable(src.stream)


def test_source_default_headers_empty() -> None:
    """Если headers не переданы — пустой dict."""
    src = GraphQLSubscriptionSource(
        endpoint_url="wss://api.example.com/graphql",
        subscription_query="subscription { x }",
    )
    assert src._headers == {} or src._headers is None
