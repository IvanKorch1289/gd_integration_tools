"""Unit tests for WorkflowBuilder."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.workflow.builder import WorkflowBuilder


class TestWorkflowBuilder:
    """Tests for :class:`WorkflowBuilder`."""

    @pytest.fixture
    def builder(self) -> WorkflowBuilder:
        return WorkflowBuilder("test.flow")

    def test_description_returns_self(self, builder: WorkflowBuilder) -> None:
        """description returns self for chaining."""
        assert builder.description("desc") is builder

    def test_max_attempts_validation(self, builder: WorkflowBuilder) -> None:
        """max_attempts rejects values < 1."""
        with pytest.raises(ValueError, match="max_attempts"):
            builder.max_attempts(0)

    def test_default_timeout_validation(self, builder: WorkflowBuilder) -> None:
        """default_timeout_s rejects non-positive values."""
        with pytest.raises(ValueError, match="default_timeout_s"):
            builder.default_timeout_s(0)

    def test_step_appends(self, builder: WorkflowBuilder) -> None:
        """step appends a sequential step."""

        async def proc(data: dict[str, Any]) -> dict[str, Any]:
            return data

        builder.step("s1", processors=[proc])
        assert builder.step_count() == 1

    def test_branch_appends(self, builder: WorkflowBuilder) -> None:
        """branch appends a branch step."""
        builder.branch(name="b1", when="true", then=[])
        assert builder.step_count() == 1

    def test_loop_validation(self, builder: WorkflowBuilder) -> None:
        """loop rejects max_iter < 1."""
        with pytest.raises(ValueError, match="max_iter"):
            builder.loop(name="l1", while_="true", body=[], max_iter=0)

    def test_loop_appends(self, builder: WorkflowBuilder) -> None:
        """loop appends a loop step."""
        builder.loop(name="l1", while_="true", body=[], max_iter=5)
        assert builder.step_count() == 1

    def test_for_each_validation(self, builder: WorkflowBuilder) -> None:
        """for_each rejects max_concurrent < 1."""
        with pytest.raises(ValueError, match="max_concurrent"):
            builder.for_each(name="f1", collection="items", body=[], max_concurrent=0)

    def test_for_each_appends(self, builder: WorkflowBuilder) -> None:
        """for_each appends a for_each step."""
        builder.for_each(name="f1", collection="items", body=[])
        assert builder.step_count() == 1

    def test_sub_workflow_appends(self, builder: WorkflowBuilder) -> None:
        """sub_workflow appends a sub_flow step."""
        builder.sub_workflow("child", name="sub")
        assert builder.step_count() == 1

    def test_trigger_workflow_is_fire_and_forget(
        self, builder: WorkflowBuilder
    ) -> None:
        """trigger_workflow sets wait=False."""
        builder.trigger_workflow("child")
        assert builder.step_count() == 1

    def test_wait_validation(self, builder: WorkflowBuilder) -> None:
        """wait requires exactly one of duration_s or until_expr."""
        with pytest.raises(ValueError, match="Either"):
            builder.wait(name="w1")
        with pytest.raises(ValueError, match="Either"):
            builder.wait(name="w1", duration_s=10, until_expr="x")

    def test_wait_appends(self, builder: WorkflowBuilder) -> None:
        """wait appends a wait step."""
        builder.wait(name="w1", duration_s=10)
        assert builder.step_count() == 1

    def test_human_approval_appends(self, builder: WorkflowBuilder) -> None:
        """human_approval appends a wait step."""
        builder.human_approval(name="h1", approvers_group="admins")
        assert builder.step_count() == 1

    def test_compensate_with_extends(self, builder: WorkflowBuilder) -> None:
        """compensate_with adds compensator steps."""
        builder.compensate_with([])
        # compensators don't count as steps
        assert builder.step_count() == 0

    def test_build_no_steps_raises(self, builder: WorkflowBuilder) -> None:
        """build raises when no steps added."""
        with pytest.raises(ValueError, match="no steps"):
            builder.build()

    def test_build_duplicate_names_raises(self, builder: WorkflowBuilder) -> None:
        """build raises when step names duplicate."""

        async def proc(data: dict[str, Any]) -> dict[str, Any]:
            return data

        builder.step("s1", processors=[proc]).step("s1", processors=[proc])
        with pytest.raises(ValueError, match="duplicate"):
            builder.build()

    def test_build_returns_processor(self, builder: WorkflowBuilder) -> None:
        """build returns a DurableWorkflowProcessor."""

        async def proc(data: dict[str, Any]) -> dict[str, Any]:
            return data

        builder.step("s1", processors=[proc])

        mock_proc = MagicMock()
        with patch(
            "src.backend.infrastructure.workflow.builder.DurableWorkflowProcessor",
            return_value=mock_proc,
        ):
            result = builder.build()

        assert result is mock_proc

    def test_name_returns_workflow_name(self, builder: WorkflowBuilder) -> None:
        """name returns the workflow name."""
        assert builder.name() == "test.flow"

    def test_repr(self, builder: WorkflowBuilder) -> None:
        """repr includes name and counts."""
        assert "WorkflowBuilder" in repr(builder)
