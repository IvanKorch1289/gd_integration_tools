"""Tests for WorkflowSubprocessProcessor (S171 M8).

Thin wrapper для запуска sub-workflow из текущего workflow.
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestWorkflowSubprocessProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
            WorkflowSubprocessProcessor,
        )
        p = WorkflowSubprocessProcessor(
            workflow_id="child_wf", input_from="body", to="body.subprocess_result"
        )
        assert p.workflow_id == "child_wf"
        assert p.input_from == "body"

    @pytest.mark.asyncio
    async def test_runs_subworkflow(self) -> None:
        from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
            WorkflowSubprocessProcessor,
        )
        p = WorkflowSubprocessProcessor(
            workflow_id="child_wf", input_from="body", to="body.subprocess_result"
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"input": "test"}  # real dict  # real dict for set_result
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        ctx = MagicMock()

        mock_result = {"output": "child completed"}
        with patch(
            "src.backend.dsl.engine.processors.workflow.workflow_subprocess.run_workflow_by_id",
            new=AsyncMock(return_value=mock_result),
        ):
            await p.process(ex, ctx)

        assert ex.in_message.body.get("subprocess_result") == mock_result

    @pytest.mark.asyncio
    async def test_handles_subworkflow_failure(self) -> None:
        """При ошибке sub-workflow — exception пробрасывается."""
        from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
            WorkflowSubprocessProcessor,
        )
        p = WorkflowSubprocessProcessor(workflow_id="missing_wf")
        ex = MagicMock()
        class _Msg:
            pass
        ex.in_message = _Msg()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        ctx = MagicMock()

        with patch(
            "src.backend.dsl.engine.processors.workflow.workflow_subprocess.run_workflow_by_id",
            new=AsyncMock(side_effect=RuntimeError("workflow not found")),
        ):
            with pytest.raises(RuntimeError, match="workflow not found"):
                await p.process(ex, ctx)


class TestWorkflowConvertProcessor:
    """Конвертация между типами (JSON ↔ YAML ↔ dict ↔ pydantic)."""

    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.workflow.workflow_convert import (
            WorkflowConvertProcessor,
        )
        p = WorkflowConvertProcessor(
            from_format="json", to_format="yaml", source_property="body.a"
        )
        assert p.from_format == "json"
        assert p.to_format == "yaml"

    @pytest.mark.asyncio
    async def test_converts_json_to_yaml(self) -> None:
        from src.backend.dsl.engine.processors.workflow.workflow_convert import (
            WorkflowConvertProcessor,
        )
        p = WorkflowConvertProcessor(
            from_format="json", to_format="yaml", source_property="body"
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"key": "value", "num": 42}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert ex.in_message.body.get("converted") is not None