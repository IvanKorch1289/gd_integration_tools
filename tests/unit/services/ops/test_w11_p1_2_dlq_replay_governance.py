"""Focused tests: W11 P1-2 — DLQ replay governance (ADR-0339).

Validation:
1. 7-step flow: inspect → classify → redact → dry-run → replay → verify → archive.
2. Capability check (fail-closed): без прав → CapabilityDeniedError.
3. Rate limit (sliding window): превышение → RateLimitExceededError.
4. PII redaction: email, phone, card_number, passport, INN, SNILS.
5. Audit trail: каждое replay создаёт ReplayAuditEntry с reason, operator_id.
6. Dry-run mode: не делает side-effects (no executor call).
7. Replay reason mandatory: пустой reason → ValueError.

ADR-0339: DLQ replay governance pattern.
"""

from __future__ import annotations

import json

import pytest

from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope, DLQReason
from src.backend.services.ops.dlq_replay_governance import (
    CapabilityDeniedError,
    DLQReplayGovernor,
    RateLimitExceededError,
    ReplayStep,
    SensitivityLevel,
)


def _make_envelope(
    *,
    payload: object = None,
    reason: DLQReason = DLQReason.TIMEOUT,
    error_class: str = "httpx.ConnectTimeout",
    error_message: str = "timeout",
    transport: str = "http",
    tenant_id: str | None = "tenant-1",
    dlq_class: str = "operational",
    retry_count: int = 3,
    metadata: dict | None = None,
) -> DLQEnvelope:
    """Helper для создания test envelope."""
    return DLQEnvelope(
        transport=transport,
        trace_id="trace-1",
        tenant_id=tenant_id,
        route_id="orders.create",
        original_payload=payload,
        error_class=error_class,
        error_message=error_message,
        reason=reason,
        retry_count=retry_count,
        dlq_class=dlq_class,
        metadata=metadata or {},
    )


class TestInspect:
    """Step 1: inspect (read-only snapshot)."""

    def test_returns_dict_with_envelope_summary(self) -> None:
        env = _make_envelope(payload={"order_id": "123"})
        governor = DLQReplayGovernor()
        snapshot = governor.inspect(env)

        assert isinstance(snapshot, dict)
        assert snapshot["dlq_id"] == env.dlq_id
        assert snapshot["transport"] == "http"
        assert snapshot["trace_id"] == "trace-1"
        assert snapshot["tenant_id"] == "tenant-1"
        assert snapshot["route_id"] == "orders.create"
        assert snapshot["error_class"] == "httpx.ConnectTimeout"
        assert snapshot["retry_count"] == 3
        assert "first_failed_at" in snapshot
        assert "last_failed_at" in snapshot

    def test_payload_size_reported(self) -> None:
        env = _make_envelope(payload="short")
        governor = DLQReplayGovernor()
        snapshot = governor.inspect(env)
        assert snapshot["payload_size"] == len("short")

    def test_payload_none_handled(self) -> None:
        env = _make_envelope(payload=None)
        governor = DLQReplayGovernor()
        snapshot = governor.inspect(env)
        assert snapshot["payload_size"] == 0


class TestClassify:
    """Step 2: classify (auto-categorization по payload + reason)."""

    def test_card_number_detected_as_financial(self) -> None:
        env = _make_envelope(payload="Card: 4111 1111 1111 1111")
        governor = DLQReplayGovernor()
        cls = governor.classify(env)
        assert cls.sensitivity == SensitivityLevel.FINANCIAL
        assert cls.requires_redaction is True
        assert "card_number" in cls.detected_patterns

    def test_email_detected_as_pii(self) -> None:
        env = _make_envelope(payload="user: alice@example.com")
        governor = DLQReplayGovernor()
        cls = governor.classify(env)
        assert cls.sensitivity == SensitivityLevel.PII
        assert cls.requires_redaction is True
        assert "email" in cls.detected_patterns

    def test_phone_detected_as_pii(self) -> None:
        env = _make_envelope(payload="+7 (495) 123-45-67")
        governor = DLQReplayGovernor()
        cls = governor.classify(env)
        assert cls.sensitivity == SensitivityLevel.PII
        assert "phone_ru" in cls.detected_patterns

    def test_inn_detected_as_pii(self) -> None:
        env = _make_envelope(payload="ИНН: 7707083893")
        governor = DLQReplayGovernor()
        cls = governor.classify(env)
        assert cls.sensitivity == SensitivityLevel.PII
        assert "inn" in cls.detected_patterns

    def test_no_pii_classified_as_internal(self) -> None:
        env = _make_envelope(payload={"order_id": "123"})
        governor = DLQReplayGovernor()
        cls = governor.classify(env)
        assert cls.sensitivity == SensitivityLevel.INTERNAL
        assert cls.requires_redaction is False
        assert cls.detected_patterns == ()

    def test_dlq_class_financial_overrides(self) -> None:
        """dlq_class='financial' → FINANCIAL даже без PII patterns."""
        env = _make_envelope(payload={"amount": 100}, dlq_class="financial")
        governor = DLQReplayGovernor()
        cls = governor.classify(env)
        assert cls.sensitivity == SensitivityLevel.FINANCIAL

    def test_capability_denied_is_internal_safe(self) -> None:
        """capability_denied reason → CONFIDENTIAL без redaction."""
        env = _make_envelope(
            payload={"auth": "secret"},
            reason=DLQReason.CAPABILITY_DENIED,
        )
        governor = DLQReplayGovernor()
        cls = governor.classify(env)
        assert cls.sensitivity == SensitivityLevel.CONFIDENTIAL
        assert cls.requires_redaction is False


class TestRedact:
    """Step 3: redact (PII replacement)."""

    def test_email_replaced(self) -> None:
        env = _make_envelope(payload="alice@example.com")
        governor = DLQReplayGovernor()
        redacted = governor.redact(env)
        assert "[REDACTED:email]" in str(redacted)
        assert "alice@example.com" not in str(redacted)

    def test_card_replaced(self) -> None:
        env = _make_envelope(payload="4111 1111 1111 1111")
        governor = DLQReplayGovernor()
        redacted = governor.redact(env)
        assert "[REDACTED:card_number]" in str(redacted)
        assert "4111 1111 1111 1111" not in str(redacted)

    def test_dict_payload_recursively_redacted(self) -> None:
        env = _make_envelope(
            payload={
                "user": {"email": "bob@test.com", "name": "Bob"},
                "order": {"id": "123"},
            }
        )
        governor = DLQReplayGovernor()
        redacted = governor.redact(env)
        assert isinstance(redacted, dict)
        assert "[REDACTED:email]" in redacted["user"]["email"]
        assert redacted["user"]["name"] == "Bob"  # non-PII preserved
        assert redacted["order"]["id"] == "123"  # non-PII preserved

    def test_json_string_redacted_recursively(self) -> None:
        env = _make_envelope(
            payload=json.dumps({"email": "x@y.com", "card": "4111111111111111"})
        )
        governor = DLQReplayGovernor()
        redacted = governor.redact(env)
        assert isinstance(redacted, dict)
        assert "[REDACTED:email]" in redacted["email"]
        assert "[REDACTED:card_number]" in redacted["card"]

    def test_no_redaction_needed_returns_original(self) -> None:
        env = _make_envelope(payload={"order_id": "123"})
        governor = DLQReplayGovernor()
        redacted = governor.redact(env)
        assert redacted == {"order_id": "123"}

    def test_custom_redactor(self) -> None:
        """Custom redactor используется вместо default (когда redaction required)."""
        env = _make_envelope(
            payload={"email": "alice@example.com"}  # PII triggers redaction
        )

        def custom_redactor(payload: object) -> object:
            return {"redacted": True, "original_type": type(payload).__name__}

        governor = DLQReplayGovernor(redactor=custom_redactor)
        redacted = governor.redact(env)
        assert redacted == {"redacted": True, "original_type": "dict"}


class TestReplayDryRun:
    """Step 4: dry-run mode (no side-effects)."""

    def test_dry_run_returns_result_with_dry_run_flag(self) -> None:
        env = _make_envelope(payload={"x": 1})
        executor_called = []

        def executor(payload: object) -> bool:
            executor_called.append(payload)
            return True

        governor = DLQReplayGovernor(replay_executor=executor)
        result = governor.replay(
            env, dry_run=True, operator_id="alice", reason="test"
        )
        assert result.step == ReplayStep.DRY_RUN
        assert result.dry_run is True
        # Executor NOT called in dry-run.
        assert executor_called == []

    def test_dry_run_skips_capability_check(self) -> None:
        """Dry-run не требует capability (read-only simulation)."""
        env = _make_envelope()

        def cap_check(cap: str, op: str) -> bool:
            return False  # would fail if called

        governor = DLQReplayGovernor(capability_check=cap_check)
        # Should NOT raise даже если capability denied.
        result = governor.replay(
            env, dry_run=True, operator_id="alice", reason="test"
        )
        assert result.success is True

    def test_dry_run_skips_rate_limit(self) -> None:
        """Dry-run не учитывается в rate limit."""
        env = _make_envelope()
        governor = DLQReplayGovernor(rate_limit_per_minute=2)

        # 5 dry-runs — все проходят (rate limit не учитывается).
        for _ in range(5):
            result = governor.replay(
                env, dry_run=True, operator_id="alice", reason="test"
            )
            assert result.success is True


class TestReplayReal:
    """Step 5: actual replay (с capability + rate limit + audit)."""

    def test_real_replay_calls_executor(self) -> None:
        env = _make_envelope(payload={"x": 1})
        executor_called = []

        def executor(payload: object) -> bool:
            executor_called.append(payload)
            return True

        governor = DLQReplayGovernor(replay_executor=executor)
        result = governor.replay(
            env, dry_run=False, operator_id="alice", reason="test"
        )
        assert result.step == ReplayStep.REPLAY
        assert result.dry_run is False
        assert result.success is True
        assert len(executor_called) == 1

    def test_empty_reason_raises_value_error(self) -> None:
        env = _make_envelope()
        governor = DLQReplayGovernor()
        with pytest.raises(ValueError, match="reason обязателен"):
            governor.replay(env, dry_run=False, operator_id="alice", reason="")
        with pytest.raises(ValueError, match="reason обязателен"):
            governor.replay(env, dry_run=False, operator_id="alice", reason="   ")

    def test_capability_denied_raises(self) -> None:
        env = _make_envelope()

        def cap_check(cap: str, op: str) -> bool:
            return False

        governor = DLQReplayGovernor(capability_check=cap_check)
        with pytest.raises(CapabilityDeniedError) as exc_info:
            governor.replay(
                env, dry_run=False, operator_id="alice", reason="test"
            )
        assert exc_info.value.capability == "dlq.replay"
        assert exc_info.value.operator_id == "alice"

    def test_capability_allowed_succeeds(self) -> None:
        env = _make_envelope()

        def cap_check(cap: str, op: str) -> bool:
            return True

        governor = DLQReplayGovernor(capability_check=cap_check)
        result = governor.replay(
            env, dry_run=False, operator_id="alice", reason="test"
        )
        assert result.success is True

    def test_rate_limit_exceeded_raises(self) -> None:
        env = _make_envelope()
        governor = DLQReplayGovernor(rate_limit_per_minute=2)

        # First 2 replays OK.
        for _ in range(2):
            governor.replay(env, dry_run=False, operator_id="alice", reason="test")

        # 3rd replay → RateLimitExceededError.
        with pytest.raises(RateLimitExceededError) as exc_info:
            governor.replay(env, dry_run=False, operator_id="alice", reason="test")
        assert exc_info.value.limit == 2
        assert exc_info.value.operator_id == "alice"

    def test_executor_exception_marked_failed(self) -> None:
        env = _make_envelope(payload={"x": 1})

        def executor(payload: object) -> bool:
            raise RuntimeError("broker down")

        governor = DLQReplayGovernor(replay_executor=executor)
        result = governor.replay(
            env, dry_run=False, operator_id="alice", reason="test"
        )
        assert result.success is False
        assert "broker down" in result.metadata.get("executor_error", "")

    def test_audit_trail_created(self) -> None:
        env = _make_envelope()
        governor = DLQReplayGovernor()
        result = governor.replay(
            env,
            dry_run=False,
            operator_id="alice",
            reason="ops-incident-42",
            correlation_id="corr-xyz",
        )
        log = governor.get_audit_log()
        assert len(log) == 1
        entry = log[0]
        assert entry.replay_id == result.replay_id
        assert entry.operator_id == "alice"
        assert entry.reason == "ops-incident-42"
        assert entry.correlation_id == "corr-xyz"
        assert entry.dry_run is False

    def test_pii_redacted_before_executor_called(self) -> None:
        """Redaction происходит ДО вызова executor."""
        env = _make_envelope(
            payload={"email": "alice@example.com", "order_id": "123"}
        )
        executor_received = []

        def executor(payload: object) -> bool:
            executor_received.append(payload)
            return True

        governor = DLQReplayGovernor(replay_executor=executor)
        result = governor.replay(
            env, dry_run=False, operator_id="alice", reason="test"
        )
        assert result.success is True
        assert len(executor_received) == 1
        # Executor получил REDACTED payload.
        payload = executor_received[0]
        assert "[REDACTED:email]" in str(payload)
        assert "alice@example.com" not in str(payload)


class TestVerify:
    """Step 6: verify (проверка audit log)."""

    def test_verify_successful_replay(self) -> None:
        env = _make_envelope()
        governor = DLQReplayGovernor()
        result = governor.replay(
            env, dry_run=False, operator_id="alice", reason="test"
        )
        assert governor.verify(result.replay_id, success=True) is True
        assert governor.verify(result.replay_id, success=False) is False

    def test_verify_nonexistent_replay(self) -> None:
        governor = DLQReplayGovernor()
        assert governor.verify("nonexistent-id", success=True) is False


class TestArchive:
    """Step 7: archive."""

    def test_archive_returns_id(self) -> None:
        env = _make_envelope()
        governor = DLQReplayGovernor()
        archive_id = governor.archive(env)
        assert isinstance(archive_id, str)
        assert len(archive_id) > 0  # UUID

    def test_archive_creates_audit_entry(self) -> None:
        env = _make_envelope()
        governor = DLQReplayGovernor()
        archive_id = governor.archive(env)
        log = governor.get_audit_log()
        assert len(log) == 1
        entry = log[0]
        assert entry.replay_id == archive_id
        assert entry.operator_id == "system"
        assert entry.reason == "archive"
        assert entry.metadata.get("step") == "archive"


class TestAuditTrailCompliance:
    """Audit trail содержит required fields для compliance."""

    def test_audit_entry_has_required_fields(self) -> None:
        env = _make_envelope()
        governor = DLQReplayGovernor()
        governor.replay(
            env,
            dry_run=False,
            operator_id="bob",
            reason="compliance-audit-2026-09",
            correlation_id="trace-123",
        )
        entry = governor.get_audit_log()[0]
        # Mandatory fields per ADR-0339.
        assert entry.replay_id
        assert entry.original_event_id
        assert entry.operator_id == "bob"
        assert entry.reason
        assert entry.correlation_id == "trace-123"
        assert entry.timestamp > 0

    def test_audit_original_event_id_from_metadata(self) -> None:
        """Если в metadata есть event_id → используется как original_event_id."""
        env = _make_envelope(metadata={"event_id": "evt-original-42"})
        governor = DLQReplayGovernor()
        governor.replay(
            env, dry_run=False, operator_id="alice", reason="test"
        )
        entry = governor.get_audit_log()[0]
        assert entry.original_event_id == "evt-original-42"

    def test_audit_original_event_id_fallback_to_dlq_id(self) -> None:
        """Без metadata.event_id → fallback на dlq_id."""
        env = _make_envelope(metadata={})
        governor = DLQReplayGovernor()
        governor.replay(
            env, dry_run=False, operator_id="alice", reason="test"
        )
        entry = governor.get_audit_log()[0]
        assert entry.original_event_id == env.dlq_id


class TestEndToEndFlow:
    """End-to-end: все 7 шагов последовательно."""

    def test_full_replay_flow_with_pii(self) -> None:
        # Setup: envelope с PII payload.
        env = _make_envelope(
            payload={
                "user_email": "alice@example.com",
                "card": "4111 1111 1111 1111",
                "order_id": "123",
            }
        )
        executor_calls: list[object] = []

        def executor(payload: object) -> bool:
            executor_calls.append(payload)
            return True

        governor = DLQReplayGovernor(
            rate_limit_per_minute=10,
            capability_check=lambda cap, op: True,
            replay_executor=executor,
        )

        # Step 1: inspect
        snapshot = governor.inspect(env)
        assert snapshot["dlq_id"] == env.dlq_id

        # Step 2: classify
        cls = governor.classify(env)
        assert cls.requires_redaction is True
        assert cls.sensitivity == SensitivityLevel.FINANCIAL

        # Step 3: redact
        redacted = governor.redact(env)
        assert "[REDACTED:email]" in str(redacted)

        # Step 4: dry-run (preview)
        dry_result = governor.replay(
            env, dry_run=True, operator_id="alice", reason="preview"
        )
        assert dry_result.dry_run is True
        assert len(executor_calls) == 0  # dry-run не вызывает executor

        # Step 5: real replay
        result = governor.replay(
            env,
            dry_run=False,
            operator_id="alice",
            reason="ops-incident-42",
            correlation_id="corr-1",
        )
        assert result.success is True
        assert len(executor_calls) == 1
        # Executor получил REDACTED payload.
        assert "[REDACTED:email]" in str(executor_calls[0])

        # Step 6: verify
        assert governor.verify(result.replay_id, success=True) is True

        # Step 7: archive
        archive_id = governor.archive(env)

        # Audit log: 3 entries (dry-run + replay + archive).
        log = governor.get_audit_log()
        assert len(log) == 3
        assert log[0].dry_run is True
        assert log[1].dry_run is False
        assert log[2].reason == "archive"
        assert log[2].replay_id == archive_id
