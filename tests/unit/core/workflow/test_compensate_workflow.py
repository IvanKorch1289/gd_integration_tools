"""TDD: CompensateWorkflow API (S171 M10 P0).

Saga-pattern compensation для multi-step workflows.
Temporal: нет native compensation — реализуем через signal + saga_state.

Pattern (Ponytail, D173): тонкая обёртка над signal_workflow.
"""
# ruff: noqa: S101
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCompensateWorkflow:
    def test_instantiates(self) -> None:
        from src.backend.core.workflow.compensation import (
            CompensateWorkflowRequest,
        )
        req = CompensateWorkflowRequest(
            workflow_id="wf-1",
            compensation_steps=["step_a", "step_b"],
            reason="downstream_failure",
        )
        assert req.workflow_id == "wf-1"
        assert req.reason == "downstream_failure"

    def test_request_serialization(self) -> None:
        from src.backend.core.workflow.compensation import (
            CompensateWorkflowRequest,
        )
        req = CompensateWorkflowRequest(
            workflow_id="wf-1",
            compensation_steps=["step_a"],
            reason="test",
        )
        # JSON-serializable
        d = req.model_dump()
        assert d["workflow_id"] == "wf-1"
        assert d["compensation_steps"] == ["step_a"]
        assert d["reason"] == "test"


class TestCompensateSignalName:
    """Имя signal должно быть стабильным (Temporal signal name contract)."""

    def test_signal_name(self) -> None:
        from src.backend.core.workflow.compensation import (
            COMPENSATE_SIGNAL,
        )
        # Stable contract: handlers должны слушать это имя
        assert COMPENSATE_SIGNAL == "_compensation_request"
