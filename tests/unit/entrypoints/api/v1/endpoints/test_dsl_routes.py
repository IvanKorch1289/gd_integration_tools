"""Unit tests for DSL routes admin endpoints."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.backend.entrypoints.api.v1.endpoints import dsl_routes as dsl_mod


class TestParseYamlOr400:
    def test_valid_yaml(self) -> None:
        with patch.object(dsl_mod, "load_pipeline_from_yaml") as mock_load:
            mock_load.return_value = MagicMock()
            result = dsl_mod._parse_yaml_or_400("yaml: test")
            assert result is mock_load.return_value

    def test_invalid_yaml_raises_400(self) -> None:
        with patch.object(
            dsl_mod, "load_pipeline_from_yaml", side_effect=ValueError("bad")
        ):
            with pytest.raises(HTTPException) as exc_info:
                dsl_mod._parse_yaml_or_400("bad")
            assert exc_info.value.status_code == 400


class TestToDetail:
    def test_builds_detail(self) -> None:
        pipeline = MagicMock()
        pipeline.route_id = "r1"
        pipeline.to_yaml.return_value = "yaml"
        pipeline.to_dict.return_value = {"spec": 1}
        pipeline.to_python.return_value = "python"
        detail = dsl_mod._to_detail(pipeline)
        assert detail.route_id == "r1"
        assert detail.yaml == "yaml"


class TestDSLRoutesFacade:
    @pytest.fixture
    def facade(self) -> dsl_mod._DSLRoutesFacade:
        return dsl_mod._DSLRoutesFacade()

    @pytest.mark.asyncio
    async def test_list_routes(self, facade: dsl_mod._DSLRoutesFacade) -> None:
        with patch.object(dsl_mod, "_yaml_store") as mock_store:
            mock_store.return_value.list.return_value = ["r1", "r2"]
            result = await facade.list_routes()
            assert result == ["r1", "r2"]

    @pytest.mark.asyncio
    async def test_get_route_not_found(self, facade: dsl_mod._DSLRoutesFacade) -> None:
        with patch.object(dsl_mod, "_yaml_store") as mock_store:
            mock_store.return_value.exists.return_value = False
            with pytest.raises(HTTPException) as exc_info:
                await facade.get_route(route_id="missing")
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_route_success(self, facade: dsl_mod._DSLRoutesFacade) -> None:
        with patch.object(dsl_mod, "_yaml_store") as mock_store:
            pipeline = MagicMock()
            pipeline.route_id = "r1"
            pipeline.to_yaml.return_value = "yaml"
            pipeline.to_dict.return_value = {}
            pipeline.to_python.return_value = "py"
            mock_store.return_value.exists.return_value = True
            mock_store.return_value.load.return_value = pipeline
            result = await facade.get_route(route_id="r1")
            assert result.route_id == "r1"

    @pytest.mark.asyncio
    async def test_create_route_conflict(
        self, facade: dsl_mod._DSLRoutesFacade
    ) -> None:
        with (
            patch.object(dsl_mod, "_yaml_store") as mock_store,
            patch.object(dsl_mod, "load_pipeline_from_yaml") as mock_load,
        ):
            pipeline = MagicMock()
            pipeline.route_id = "r1"
            mock_load.return_value = pipeline
            mock_store.return_value.exists.return_value = True
            with pytest.raises(HTTPException) as exc_info:
                await facade.create_route(yaml="yaml")
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_create_route_success(self, facade: dsl_mod._DSLRoutesFacade) -> None:
        with (
            patch.object(dsl_mod, "_yaml_store") as mock_store,
            patch.object(dsl_mod, "load_pipeline_from_yaml") as mock_load,
        ):
            pipeline = MagicMock()
            pipeline.route_id = "r1"
            pipeline.to_yaml.return_value = "yaml"
            pipeline.to_dict.return_value = {}
            pipeline.to_python.return_value = "py"
            mock_load.return_value = pipeline
            mock_store.return_value.exists.return_value = False
            result = await facade.create_route(yaml="yaml")
            assert result.route_id == "r1"

    @pytest.mark.asyncio
    async def test_update_route_not_found(
        self, facade: dsl_mod._DSLRoutesFacade
    ) -> None:
        with patch.object(dsl_mod, "_yaml_store") as mock_store:
            mock_store.return_value.exists.return_value = False
            with pytest.raises(HTTPException) as exc_info:
                await facade.update_route(route_id="r1", yaml="yaml")
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_route_mismatch(
        self, facade: dsl_mod._DSLRoutesFacade
    ) -> None:
        with (
            patch.object(dsl_mod, "_yaml_store") as mock_store,
            patch.object(dsl_mod, "load_pipeline_from_yaml") as mock_load,
        ):
            pipeline = MagicMock()
            pipeline.route_id = "r2"
            mock_load.return_value = pipeline
            mock_store.return_value.exists.return_value = True
            with pytest.raises(HTTPException) as exc_info:
                await facade.update_route(route_id="r1", yaml="yaml")
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_route_not_found(
        self, facade: dsl_mod._DSLRoutesFacade
    ) -> None:
        with patch.object(dsl_mod, "_yaml_store") as mock_store:
            mock_store.return_value.delete.return_value = False
            with pytest.raises(HTTPException) as exc_info:
                await facade.delete_route(route_id="r1")
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_validate_route_invalid(
        self, facade: dsl_mod._DSLRoutesFacade
    ) -> None:
        with patch.object(
            dsl_mod, "load_pipeline_from_yaml", side_effect=ValueError("bad")
        ):
            result = await facade.validate_route(yaml="bad")
            assert result.valid is False
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_validate_route_valid(self, facade: dsl_mod._DSLRoutesFacade) -> None:
        with patch.object(dsl_mod, "load_pipeline_from_yaml") as mock_load:
            pipeline = MagicMock()
            pipeline.route_id = "r1"
            pipeline.processors = [1, 2, 3]
            mock_load.return_value = pipeline
            result = await facade.validate_route(yaml="yaml")
            assert result.valid is True
            assert result.processors_count == 3

    @pytest.mark.asyncio
    async def test_diff_route_not_found(self, facade: dsl_mod._DSLRoutesFacade) -> None:
        with patch.object(dsl_mod, "_yaml_store") as mock_store:
            mock_store.return_value.exists.return_value = False
            with pytest.raises(HTTPException) as exc_info:
                await facade.diff_route(route_id="r1", yaml="yaml")
            assert exc_info.value.status_code == 404


class TestGetRoutePython:
    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        with patch.object(dsl_mod, "_yaml_store") as mock_store:
            mock_store.return_value.exists.return_value = False
            with pytest.raises(HTTPException) as exc_info:
                await dsl_mod._get_route_python("r1")
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_python(self) -> None:
        with patch.object(dsl_mod, "_yaml_store") as mock_store:
            pipeline = MagicMock()
            pipeline.to_python.return_value = "python code"
            mock_store.return_value.exists.return_value = True
            mock_store.return_value.load.return_value = pipeline
            resp = await dsl_mod._get_route_python("r1")
            assert resp.media_type == "text/plain"
            assert resp.body == b"python code"
