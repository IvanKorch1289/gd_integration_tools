"""Sprint 30 (C): tests for src/backend/dsl/workflow/spec/activity_declarations.py.

6 Pydantic v2 BaseModel declarations used in WorkflowBuilder:
* ActivityDeclaration — atomic Temporal activity
* SagaDeclaration — forward + compensate steps
* PauseDeclaration / ResumeDeclaration — pause/resume control
* SignalWaitDeclaration — wait for external signal
* SleepDeclaration — time-based wait

Coverage was 0% before Sprint 30.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestActivityDeclaration:
    """ActivityDeclaration — atomic Temporal activity spec."""

    def test_minimal_valid(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            ActivityDeclaration,
        )

        d = ActivityDeclaration(name="my_activity")
        assert d.type == "activity"
        assert d.name == "my_activity"
        assert d.args == {}
        assert d.timeout_s is None
        assert d.retry_policy is None
        assert d.output_key is None
        assert d.required_capabilities == ()

    def test_name_required(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            ActivityDeclaration,
        )

        with pytest.raises(ValidationError):
            ActivityDeclaration(name="")  # min_length=1

    def test_full_args(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            ActivityDeclaration,
        )

        d = ActivityDeclaration(
            name="charge_card",
            args={"amount": 100, "currency": "USD"},
            timeout_s=30.0,
            output_key="result",
            required_capabilities=("payments.write",),
        )
        assert d.args == {"amount": 100, "currency": "USD"}
        assert d.timeout_s == 30.0
        assert d.output_key == "result"
        assert d.required_capabilities == ("payments.write",)

    def test_timeout_must_be_positive(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            ActivityDeclaration,
        )

        with pytest.raises(ValidationError):
            ActivityDeclaration(name="x", timeout_s=0.0)
        with pytest.raises(ValidationError):
            ActivityDeclaration(name="x", timeout_s=-1.0)

    def test_extra_fields_forbidden(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            ActivityDeclaration,
        )

        # extra="forbid" → unknown fields raise ValidationError
        with pytest.raises(ValidationError):
            ActivityDeclaration(name="x", unknown_field="bad")

    def test_serialization_roundtrip(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            ActivityDeclaration,
        )

        d = ActivityDeclaration(name="x", args={"a": 1})
        # JSON roundtrip
        json_str = d.model_dump_json()
        d2 = ActivityDeclaration.model_validate_json(json_str)
        assert d2 == d


class TestPauseResumeDeclarations:
    """Pause/Resume — control flow for HITL (Human-in-the-Loop)."""

    def test_pause_default(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            PauseDeclaration,
        )

        d = PauseDeclaration()
        assert d.type == "pause"

    def test_resume_default(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            ResumeDeclaration,
        )

        d = ResumeDeclaration()
        assert d.type == "resume"


class TestSignalWaitDeclaration:
    """SignalWait — wait for external signal during workflow."""

    def test_minimal(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            SignalWaitDeclaration,
        )

        d = SignalWaitDeclaration(signal_name="payment_confirmed")
        assert d.type == "wait_signal"
        assert d.signal_name == "payment_confirmed"
        assert d.on_timeout == "raise"  # fail-loud default

    def test_with_timeout_and_on_timeout(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            SignalWaitDeclaration,
        )

        d = SignalWaitDeclaration(
            signal_name="approval",
            timeout_s=60.0,
            on_timeout="continue",
            output_key="approval_payload",
        )
        assert d.timeout_s == 60.0
        assert d.on_timeout == "continue"
        assert d.output_key == "approval_payload"


class TestSleepDeclaration:
    """Sleep — time-based wait in workflow."""

    def test_sleep_with_duration(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            SleepDeclaration,
        )

        d = SleepDeclaration(duration_s=30.0)
        assert d.type == "sleep"
        assert d.duration_s == 30.0

    def test_sleep_must_be_positive(self) -> None:
        from src.backend.dsl.workflow.spec.activity_declarations import (
            SleepDeclaration,
        )

        with pytest.raises(ValidationError):
            SleepDeclaration(duration_s=0.0)
        with pytest.raises(ValidationError):
            SleepDeclaration(duration_s=-1.0)
