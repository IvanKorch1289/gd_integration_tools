"""Tests for ``src.backend.entrypoints.graphql.dsl_result``.

S168 W12 P2-4: GraphQL DSL result types (DslResult, ActionResult, dispatch_action).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.graphql import dsl_result as mod
from src.backend.entrypoints.graphql.dsl_result import (
    ActionResult,
    DslResult,
    dispatch_action,
)


class TestDslResultType:
    """DslResult — strawberry.type."""

    def test_importable(self) -> None:
        assert DslResult is not None

    def test_has_required_fields(self) -> None:
        # Strawberry fields — это StrawberryField объекты с .name
        field_names = {f.name for f in DslResult.__strawberry_definition__.fields}
        assert "route_id" in field_names
        assert "status" in field_names
        assert "result" in field_names
        assert "error" in field_names

    def test_construction(self) -> None:
        # Strawberry type — конструктор принимает kwargs
        result = DslResult(route_id="r1", status="ok")
        assert result.route_id == "r1"
        assert result.status == "ok"
        assert result.result is None
        assert result.error is None

    def test_with_result(self) -> None:
        result = DslResult(route_id="r1", status="ok", result={"data": 1})
        assert result.result == {"data": 1}

    def test_with_error(self) -> None:
        result = DslResult(route_id="r1", status="error", error="some error")
        assert result.error == "some error"


class TestActionResultType:
    """ActionResult — strawberry.type."""

    def test_importable(self) -> None:
        assert ActionResult is not None

    def test_has_required_fields(self) -> None:
        field_names = {f.name for f in ActionResult.__strawberry_definition__.fields}
        assert "action" in field_names
        assert "success" in field_names
        assert "data" in field_names
        assert "error" in field_names

    def test_construction(self) -> None:
        result = ActionResult(action="my_action", success=True)
        assert result.action == "my_action"
        assert result.success is True
        assert result.data is None
        assert result.error is None

    def test_with_data(self) -> None:
        result = ActionResult(action="a", success=True, data={"x": 1})
        assert result.data == {"x": 1}

    def test_with_error(self) -> None:
        result = ActionResult(action="a", success=False, error="boom")
        assert result.error == "boom"
        assert result.success is False


class TestDispatchActionSuccess:
    """dispatch_action() — success path."""

    @pytest.mark.asyncio
    async def test_simple_dict_result(self) -> None:
        mock_dispatch = AsyncMock(return_value={"result": "ok"})

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("test_action", {"k": "v"})

        assert isinstance(result, ActionResult)
        assert result.action == "test_action"
        assert result.success is True
        assert result.data == {"result": "ok"}
        assert result.error is None

    @pytest.mark.asyncio
    async def test_pydantic_result_with_model_dump(self) -> None:
        # Если result — Pydantic model, используется model_dump
        mock_pydantic = MagicMock()
        mock_pydantic.model_dump = MagicMock(return_value={"id": 1, "name": "x"})

        mock_dispatch = AsyncMock(return_value=mock_pydantic)

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("get_item", {"id": 1})

        assert result.success is True
        assert result.data == {"id": 1, "name": "x"}
        mock_pydantic.model_dump.assert_called_once_with(mode="json")

    @pytest.mark.asyncio
    async def test_object_with_dict_result(self) -> None:
        # Если result — object с __dict__, используется __dict__
        mock_obj = MagicMock(spec=["x", "y"])
        mock_obj.x = 1
        mock_obj.y = "two"

        mock_dispatch = AsyncMock(return_value=mock_obj)

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("complex_action")

        assert result.success is True
        # __dict__ содержит spec'd attributes
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_no_payload(self) -> None:
        mock_dispatch = AsyncMock(return_value={"ok": True})

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("ping")

        assert result.success is True
        # payload=None передан
        mock_dispatch.assert_called_once_with(
            action="ping", payload=None, source="graphql"
        )

    @pytest.mark.asyncio
    async def test_source_is_graphql(self) -> None:
        # source="graphql" передаётся в unified dispatch
        mock_dispatch = AsyncMock(return_value={})

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            await dispatch_action("a", {})

        # Проверяем source
        call_kwargs = mock_dispatch.call_args.kwargs
        assert call_kwargs["source"] == "graphql"


class TestDispatchActionKeyError:
    """KeyError → action not registered."""

    @pytest.mark.asyncio
    async def test_keyerror_returns_failure(self) -> None:
        mock_dispatch = AsyncMock(side_effect=KeyError("action not found"))

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("unknown_action")

        assert result.success is False
        assert "не зарегистрирован" in result.error
        assert "unknown_action" in result.error

    @pytest.mark.asyncio
    async def test_keyerror_data_is_none(self) -> None:
        mock_dispatch = AsyncMock(side_effect=KeyError("missing"))

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("missing")

        assert result.data is None
        assert result.success is False


class TestDispatchActionGenericError:
    """Любое другое исключение → failure."""

    @pytest.mark.asyncio
    async def test_value_error_caught(self) -> None:
        mock_dispatch = AsyncMock(side_effect=ValueError("bad value"))

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("explode")

        assert result.success is False
        assert "упал" in result.error
        assert "bad value" in result.error

    @pytest.mark.asyncio
    async def test_runtime_error_caught(self) -> None:
        mock_dispatch = AsyncMock(side_effect=RuntimeError("boom"))

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("explode")

        assert result.success is False
        assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_generic_exception_caught(self) -> None:
        mock_dispatch = AsyncMock(side_effect=Exception("generic"))

        with patch(
            "src.backend.entrypoints.base.dispatch_action", mock_dispatch
        ):
            result = await dispatch_action("explode")

        assert result.success is False
        assert "generic" in result.error


class TestAllExports:
    """__all__ проверка."""

    def test_exports_two_types_and_function(self) -> None:
        assert "DslResult" in mod.__all__
        assert "ActionResult" in mod.__all__
        assert "dispatch_action" in mod.__all__
        assert len(mod.__all__) == 3

    def test_function_callable(self) -> None:
        assert callable(dispatch_action)


class TestModuleImport:
    """Smoke import."""

    def test_module_imports(self) -> None:
        from src.backend.entrypoints.graphql import dsl_result as m

        assert m is mod