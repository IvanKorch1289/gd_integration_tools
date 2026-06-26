"""TDD: WorkflowContinueAsNewProcessor + WorkflowClaimCheckProcessor."""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest


class TestWorkflowContinueAsNewProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new import (
            WorkflowContinueAsNewProcessor,
        )
        p = WorkflowContinueAsNewProcessor(
            same_workflow_id=True, same_input=True
        )
        assert p.same_workflow_id is True

    @pytest.mark.asyncio
    async def test_continue_with_marker(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new import (
            WorkflowContinueAsNewProcessor,
        )
        p = WorkflowContinueAsNewProcessor(same_workflow_id=True)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"step": 50}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        ex.set_property.assert_called_once()
        args, _ = ex.set_property.call_args
        assert "continue_as_new_requested" in args[0]


class TestWorkflowClaimCheckProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )
        p = WorkflowClaimCheckProcessor(
            source_property="body.payload",
            max_size_bytes=100,
            storage_backend="s3",
            bucket="payloads",
        )
        assert p.storage_backend == "s3"
        assert p.bucket == "payloads"

    @pytest.mark.asyncio
    async def test_store_oversized_payload(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )
        p = WorkflowClaimCheckProcessor(
            source_property="body.payload",
            max_size_bytes=100,
            storage_backend="s3",
            bucket="payloads",
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"payload": {"large": "x" * 1000}}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert ex.in_message.body.get("payload_claim") is not None
