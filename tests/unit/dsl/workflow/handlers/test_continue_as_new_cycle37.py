"""TDD cycle 37: ContinueAsNew TypeError fix.

Reproduces the bug:
`temporalio.workflow.continue_as_new()` does NOT accept ``search_attributes``
kwarg — это отдельный метод ``workflow.upsert_search_attributes(...)``.

The fix splits the call: upsert SA first (defensive skip on empty), then
``workflow.continue_as_new(args["input"])`` with only the input payload.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock


def _install_fake_temporalio() -> MagicMock:
    """Подменяем ``temporalio.workflow`` на MagicMock (lazy import).

    Привязываем ``temporalio.workflow`` как атрибут к ``temporalio``,
    чтобы ``from temporalio import workflow`` корректно нашёл мок.
    """
    workflow_mock = MagicMock()
    temporalio_module = MagicMock()
    temporalio_module.workflow = workflow_mock
    sys.modules["temporalio"] = temporalio_module
    sys.modules["temporalio.workflow"] = workflow_mock
    return workflow_mock


def _uninstall_fake_temporalio() -> None:
    """Убираем подмену sys.modules."""
    sys.modules.pop("temporalio", None)
    sys.modules.pop("temporalio.workflow", None)


def _build_handler_with_marker(
    *,
    same_input: bool = False,
    body_snapshot: dict | None = None,
    search_attributes: dict | None = None,
) -> tuple:
    """Construct handler + marker dict for ``perform_continue``."""
    from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
        ContinueAsNewHandler,
    )

    h = ContinueAsNewHandler()
    marker = {
        "requested": True,
        "same_workflow_id": True,
        "same_input": same_input,
        "search_attributes": search_attributes if search_attributes is not None else {},
        "body_snapshot": body_snapshot if body_snapshot is not None else {},
    }
    return h, marker


class TestContinueAsNewCycle37:
    """B-18 fix (cycle 37): TypeError split into upsert + continue_as_new."""

    def test_perform_continue_calls_upsert_then_continue_with_payload(self) -> None:
        """upsert_search_attributes получает SA; continue_as_new получает ТОЛЬКО input."""
        h, marker = _build_handler_with_marker(
            search_attributes={"env": "prod", "tenant_id": "t-1"},
            body_snapshot={"step": 100},
        )

        fake_workflow = _install_fake_temporalio()
        try:
            h.perform_continue(marker, current_input={"orig": "x"})
        finally:
            _uninstall_fake_temporalio()

        # SA были переданы в upsert_search_attributes
        fake_workflow.upsert_search_attributes.assert_called_once_with(
            {"env": "prod", "tenant_id": "t-1"}
        )
        # continue_as_new получил только input (НЕ search_attributes)
        fake_workflow.continue_as_new.assert_called_once_with({"step": 100})
        # порядок: оба вызваны по одному разу
        assert (
            fake_workflow.upsert_search_attributes.call_count == 1
            and fake_workflow.continue_as_new.call_count == 1
        )

    def test_perform_continue_no_search_attrs_skips_upsert(self) -> None:
        """Если search_attributes пустой — skip upsert, не вызывать вообще."""
        h, marker = _build_handler_with_marker(
            search_attributes={},
            body_snapshot={"step": 5},
        )

        fake_workflow = _install_fake_temporalio()
        try:
            h.perform_continue(marker, current_input={"orig": "x"})
        finally:
            _uninstall_fake_temporalio()

        # upsert НЕ вызван (defensive skip)
        fake_workflow.upsert_search_attributes.assert_not_called()
        # continue_as_new вызван с input
        fake_workflow.continue_as_new.assert_called_once_with({"step": 5})

    def test_perform_continue_input_as_dict_passes_as_single_arg(self) -> None:
        """ВСЕГДА передаём input одним kwarg (без **kwargs), без TypeError."""
        h, marker = _build_handler_with_marker(
            search_attributes={"k": "v"},
            body_snapshot={"a": 1, "b": [1, 2]},
        )

        fake_workflow = _install_fake_temporalio()
        try:
            # Должно пройти без TypeError
            h.perform_continue(marker, current_input={"orig": "x"})
        finally:
            _uninstall_fake_temporalio()

        # continue_as_new получил input dict (а НЕ search_attributes)
        call_args = fake_workflow.continue_as_new.call_args
        assert call_args is not None
        # positional args
        assert call_args.args == ({"a": 1, "b": [1, 2]},)
        # никаких kwargs (особенно НЕ search_attributes)
        assert "search_attributes" not in call_args.kwargs
