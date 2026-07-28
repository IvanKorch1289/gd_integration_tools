"""Tests for core.workflow.compensation (Layer 2, cycle 41 review fix).

The compensation Saga primitive was previously untested. Cycle 41 review
identified this as a Layer 2 gap.

Tests focus on:
- COMPENSATE_SIGNAL constant stability (Temporal signal contract)
- CompensateWorkflowRequest Pydantic model: validation, defaults, immutability
- Round-trip serialization for Temporal workflow communication
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.workflow.compensation import (
    COMPENSATE_SIGNAL,
    CompensateWorkflowRequest,
)


class TestCompensateSignalConstant:
    """COMPENSATE_SIGNAL is a stable string for Temporal signal routing.

    Workers listen for this signal name to trigger compensation. Changing
    the value would break compatibility with running workflows.
    """

    def test_signal_name_stable(self) -> None:
        """The signal name MUST stay '_compensation_request'."""
        assert COMPENSATE_SIGNAL == "_compensation_request"

    def test_signal_is_string(self) -> None:
        """Signal name must be a string (Temporal signal contract)."""
        assert isinstance(COMPENSATE_SIGNAL, str)
        assert len(COMPENSATE_SIGNAL) > 0


class TestCompensateWorkflowRequest:
    """CompensateWorkflowRequest: Saga compensation request payload."""

    def test_minimal_required_fields(self) -> None:
        """workflow_id and reason are required; everything else defaults."""
        req = CompensateWorkflowRequest(
            workflow_id="wf-123",
            reason="step_3_failed",
        )
        assert req.workflow_id == "wf-123"
        assert req.reason == "step_3_failed"
        assert req.compensation_steps == []  # default empty list
        assert req.metadata == {}  # default empty dict

    def test_compensation_steps_default_to_empty_list(self) -> None:
        """compensation_steps default to [] (not None) to avoid type errors downstream."""
        req = CompensateWorkflowRequest(workflow_id="wf-1", reason="x")
        assert req.compensation_steps == []
        assert isinstance(req.compensation_steps, list)

    def test_metadata_default_to_empty_dict(self) -> None:
        req = CompensateWorkflowRequest(workflow_id="wf-1", reason="x")
        assert req.metadata == {}
        assert isinstance(req.metadata, dict)

    def test_full_request_with_all_fields(self) -> None:
        req = CompensateWorkflowRequest(
            workflow_id="wf-abc",
            compensation_steps=["step_5", "step_3", "step_1"],
            reason="downstream_unavailable",
            metadata={"tenant_id": "tenant:acme", "trace_id": "abc-123"},
        )
        assert req.workflow_id == "wf-abc"
        assert req.compensation_steps == ["step_5", "step_3", "step_1"]
        assert req.reason == "downstream_unavailable"
        assert req.metadata["tenant_id"] == "tenant:acme"
        assert req.metadata["trace_id"] == "abc-123"

    def test_missing_workflow_id_raises(self) -> None:
        """workflow_id is required (Pydantic validation)."""
        with pytest.raises(ValidationError):
            CompensateWorkflowRequest(reason="step_failed")

    def test_missing_reason_raises(self) -> None:
        """reason is required (Pydantic validation)."""
        with pytest.raises(ValidationError):
            CompensateWorkflowRequest(workflow_id="wf-1")

    def test_compensation_steps_accept_any_order(self) -> None:
        """compensation_steps order is the caller's responsibility.

        Producer is expected to put steps in reverse execution order
        (most-recent first). Consumer (workflow handler) executes in given
        order. We don't enforce order here — domain logic is in the
        consumer.
        """
        # Forward order (caller mistake)
        req1 = CompensateWorkflowRequest(
            workflow_id="wf", reason="r", compensation_steps=["step1", "step2"]
        )
        assert req1.compensation_steps == ["step1", "step2"]

        # Reverse order (correct usage)
        req2 = CompensateWorkflowRequest(
            workflow_id="wf", reason="r", compensation_steps=["step2", "step1"]
        )
        assert req2.compensation_steps == ["step2", "step1"]


class TestCompensateWorkflowRequestSerialization:
    """Round-trip serialization for Temporal workflow signal."""

    def test_json_roundtrip(self) -> None:
        """Request can be serialized to JSON and back (Temporal payload)."""
        original = CompensateWorkflowRequest(
            workflow_id="wf-999",
            compensation_steps=["step3", "step1"],
            reason="external_api_5xx",
            metadata={"tenant": "tenant:foo"},
        )
        json_payload = original.model_dump_json()
        restored = CompensateWorkflowRequest.model_validate_json(json_payload)

        assert restored.workflow_id == original.workflow_id
        assert restored.compensation_steps == original.compensation_steps
        assert restored.reason == original.reason
        assert restored.metadata == original.metadata

    def test_json_roundtrip_with_empty_defaults(self) -> None:
        """Defaults are preserved through JSON round-trip."""
        original = CompensateWorkflowRequest(workflow_id="wf-1", reason="x")
        json_payload = original.model_dump_json()
        restored = CompensateWorkflowRequest.model_validate_json(json_payload)

        assert restored.compensation_steps == []
        assert restored.metadata == {}
