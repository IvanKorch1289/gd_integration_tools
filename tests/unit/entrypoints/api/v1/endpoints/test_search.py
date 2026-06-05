"""Unit tests for search endpoints."""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.entrypoints.api.v1.endpoints import search as search_mod


class TestBuildTextQuery:
    def test_empty(self) -> None:
        q = search_mod._build_text_query(None)
        assert q == {"match_all": {}}

    def test_with_q_no_fields(self) -> None:
        q = search_mod._build_text_query("hello")
        assert "query_string" in q["bool"]["must"][0]

    def test_with_q_and_fields(self) -> None:
        q = search_mod._build_text_query("hello", fields=["title", "body"])
        assert "multi_match" in q["bool"]["must"][0]

    def test_with_filters(self) -> None:
        q = search_mod._build_text_query(None, filters={"status": "open"})
        assert q["bool"]["filter"][0] == {"term": {"status": "open"}}

    def test_with_range(self) -> None:
        q = search_mod._build_text_query(
            None, range_filter={"date": {"gte": "2024-01-01"}}
        )
        assert q["bool"]["filter"][0] == {"range": {"date": {"gte": "2024-01-01"}}}


class TestDateRange:
    def test_both_none(self) -> None:
        assert search_mod._date_range(None, None, "d") == {}

    def test_from_only(self) -> None:
        dt = datetime(2024, 1, 1, 12, 0, 0)
        result = search_mod._date_range(dt, None, "d")
        assert result == {"d": {"gte": dt.isoformat()}}

    def test_to_only(self) -> None:
        dt = datetime(2024, 1, 1, 12, 0, 0)
        result = search_mod._date_range(None, dt, "d")
        assert result == {"d": {"lte": dt.isoformat()}}


class TestSafeSearch:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch.object(search_mod, "get_search_service") as mock_get:
            svc = AsyncMock()
            svc.search.return_value = [{"id": 1}]
            mock_get.return_value = svc
            result = await search_mod._safe_search("idx", {}, limit=10, offset=0)
            assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_failure_returns_empty(self) -> None:
        with patch.object(search_mod, "get_search_service") as mock_get:
            mock_get.side_effect = RuntimeError("fail")
            result = await search_mod._safe_search("idx", {}, limit=10, offset=0)
            assert result == []


class TestSearchFacade:
    @pytest.fixture
    def facade(self) -> search_mod._SearchFacade:
        return search_mod._SearchFacade()

    @pytest.mark.asyncio
    async def test_search_logs(self, facade: search_mod._SearchFacade) -> None:
        with patch.object(
            search_mod, "_safe_search", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = [{"id": 1}]
            result = await facade.search_logs(q="test", limit=5)
            assert result == [{"id": 1}]
            mock_search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_orders(self, facade: search_mod._SearchFacade) -> None:
        with patch.object(
            search_mod, "_safe_search", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = []
            result = await facade.search_orders(status="open")
            assert result == []

    @pytest.mark.asyncio
    async def test_search_notebooks(self, facade: search_mod._SearchFacade) -> None:
        with patch.object(
            search_mod, "_safe_search", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = [{"title": "nb1"}]
            result = await facade.search_notebooks(q="ml")
            assert result == [{"title": "nb1"}]

    @pytest.mark.asyncio
    async def test_aggregate(self, facade: search_mod._SearchFacade) -> None:
        with patch.object(search_mod, "get_search_service") as mock_get:
            svc = AsyncMock()
            svc.aggregate.return_value = {"buckets": []}
            mock_get.return_value = svc
            result = await facade.aggregate(index="orders", field="status")
            assert result == {"buckets": []}

    @pytest.mark.asyncio
    async def test_aggregate_failure(self, facade: search_mod._SearchFacade) -> None:
        with patch.object(search_mod, "get_search_service") as mock_get:
            mock_get.side_effect = RuntimeError("fail")
            result = await facade.aggregate(index="orders", field="status")
            assert result == {}

    @pytest.mark.asyncio
    async def test_facets(self, facade: search_mod._SearchFacade) -> None:
        with patch.object(search_mod, "get_search_service") as mock_get:
            svc = AsyncMock()
            svc.aggregate_terms.return_value = {"buckets": [{"key": "a", "count": 5}]}
            mock_get.return_value = svc
            result = await facade.facets(index="orders", field="status")
            assert "buckets" in result

    @pytest.mark.asyncio
    async def test_facets_invalid_filter(
        self, facade: search_mod._SearchFacade
    ) -> None:
        with patch.object(search_mod, "get_search_service") as mock_get:
            svc = AsyncMock()
            svc.aggregate_terms.return_value = {}
            mock_get.return_value = svc
            result = await facade.facets(
                index="orders", field="status", filter="not-json"
            )
            assert result == {}

    @pytest.mark.asyncio
    async def test_facets_failure(self, facade: search_mod._SearchFacade) -> None:
        with patch.object(search_mod, "get_search_service") as mock_get:
            mock_get.side_effect = RuntimeError("fail")
            result = await facade.facets(index="orders", field="status")
            assert result == {}
