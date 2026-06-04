"""Tests for dsl/routes.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.routes import (
    _default_payload_factory,
    _register_action_route,
    register_dsl_routes,
)


@pytest.fixture(autouse=True)
def _disable_action_validation():
    with patch("src.backend.dsl.builders.base.RouteBuilder._validate_action_names"):
        yield


class TestDefaultPayloadFactory:
    def test_dict_body(self) -> None:
        ex = MagicMock()
        ex.in_message.body = {"x": 1}
        assert _default_payload_factory(ex) == {"x": 1}

    def test_non_dict_body(self) -> None:
        ex = MagicMock()
        ex.in_message.body = "text"
        assert _default_payload_factory(ex) == {}


class TestRegisterActionRoute:
    def test_registers_route(self) -> None:
        mock_registry = MagicMock()
        with (
            patch("src.backend.dsl.routes.action_handler_registry") as ahr,
            patch("src.backend.dsl.routes.route_registry", mock_registry),
        ):
            ahr.list_actions.return_value = ["orders.create"]
            _register_action_route("orders.create")
        mock_registry.register.assert_called_once()
        route = mock_registry.register.call_args[0][0]
        assert route.route_id == "orders.create"


class TestRegisterDslRoutes:
    def test_iterates_actions(self) -> None:
        mock_registry = MagicMock()
        with (
            patch("src.backend.dsl.routes.action_handler_registry") as ahr,
            patch("src.backend.dsl.routes.route_registry", mock_registry),
        ):
            ahr.list_actions.return_value = ["a1", "a2"]
            register_dsl_routes()
        assert mock_registry.register.call_count == 2
