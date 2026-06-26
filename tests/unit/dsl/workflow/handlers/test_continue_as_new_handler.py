"""TDD: ContinueAsNew runtime handler (S171 M10 P0).

Per Temporal best practice, после process() в DSL ставится marker в exchange.
Worker (или activity step) должен прочитать marker и вызвать
``temporalio.workflow.continue_as_new()``.

Pattern (Ponytail, D169): handler — тонкая обёртка, lazy temporalio import.
"""
# ruff: noqa: S101
from __future__ import annotations
from unittest.mock import MagicMock

import pytest


class TestContinueAsNewHandler:
    def test_instantiates(self) -> None:
        from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
            ContinueAsNewHandler,
        )
        h = ContinueAsNewHandler()
        assert h is not None

    def test_extract_marker(self) -> None:
        from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
            ContinueAsNewHandler,
        )
        h = ContinueAsNewHandler()
        exchange = MagicMock()
        exchange.in_message = MagicMock()
        exchange.in_message.body = {
            "step": 100,
            "continue_as_new_requested": {
                "requested": True,
                "same_workflow_id": True,
                "same_input": False,
                "search_attributes": {"env": "prod"},
                "body_snapshot": {"step": 100},
            },
        }
        marker = h.extract_marker(exchange)
        assert marker is not None
        assert marker["requested"] is True

    def test_extract_marker_returns_none_if_no_marker(self) -> None:
        from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
            ContinueAsNewHandler,
        )
        h = ContinueAsNewHandler()
        exchange = MagicMock()
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"step": 50}
        assert h.extract_marker(exchange) is None

    def test_should_continue_returns_false_if_no_marker(self) -> None:
        from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
            ContinueAsNewHandler,
        )
        h = ContinueAsNewHandler()
        exchange = MagicMock()
        exchange.in_message = MagicMock()
        exchange.in_message.body = {}
        assert h.should_continue(exchange) is False

    def test_should_continue_returns_true_if_marker(self) -> None:
        from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
            ContinueAsNewHandler,
        )
        h = ContinueAsNewHandler()
        exchange = MagicMock()
        exchange.in_message = MagicMock()
        exchange.in_message.body = {
            "continue_as_new_requested": {"requested": True, "same_workflow_id": True}
        }
        assert h.should_continue(exchange) is True

    def test_build_continue_args(self) -> None:
        from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
            ContinueAsNewHandler,
        )
        h = ContinueAsNewHandler()
        marker = {
            "requested": True,
            "same_workflow_id": True,
            "same_input": False,
            "search_attributes": {"env": "prod"},
            "body_snapshot": {"step": 100},
        }
        args = h.build_continue_args(marker, current_input={"orig": "x"})
        assert "input" in args
        assert args["input"] == {"step": 100}
        assert args["search_attributes"] == {"env": "prod"}
