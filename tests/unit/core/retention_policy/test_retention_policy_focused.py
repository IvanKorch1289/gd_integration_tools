"""Focused tests for ``core.retention_policy`` (Wave 4 #74)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.backend.core.retention_policy import (
    LegalHold,
    RetentionAction,
    RetentionEngine,
    RetentionPolicy,
    RetentionVerdict,
    get_retention_engine,
)
from src.backend.core.retention_policy.engine import _days_ago, reset_retention_engine


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_retention_engine()


class TestRetentionAction:
    def test_values(self) -> None:
        assert RetentionAction.KEEP.value == "keep"
        assert RetentionAction.ARCHIVE.value == "archive"
        assert RetentionAction.ANONYMIZE.value == "anonymize"
        assert RetentionAction.DELETE.value == "delete"


class TestRetentionPolicy:
    def test_defaults(self) -> None:
        p = RetentionPolicy(data_type="x", retention_days=30)
        assert p.action == RetentionAction.DELETE
        assert p.anonymize_fields == ()

    def test_with_anonymize(self) -> None:
        p = RetentionPolicy(
            data_type="user_data",
            retention_days=365,
            action=RetentionAction.ANONYMIZE,
            anonymize_fields=("email", "phone"),
        )
        assert "email" in p.anonymize_fields


class TestLegalHold:
    def test_init(self) -> None:
        h = LegalHold(
            data_type="audit_log",
            reason="investigation-123",
            created_at=datetime.now(UTC).isoformat(),
        )
        assert h.expires_at is None

    def test_with_expiry(self) -> None:
        h = LegalHold(
            data_type="x",
            reason="r",
            created_at="2026-01-01T00:00:00",
            expires_at="2027-01-01T00:00:00",
        )
        assert h.expires_at == "2027-01-01T00:00:00"


class TestRetentionVerdict:
    def test_defaults(self) -> None:
        v = RetentionVerdict(data_type="x", age_days=10, action=RetentionAction.KEEP)
        assert v.reason == ""
        assert v.blocked_by_hold is False


class TestEngineInit:
    def test_init(self) -> None:
        e = RetentionEngine()
        assert e.policy_count() == 0
        assert e.list_policies() == []
        assert e.list_holds() == []


class TestRegisterPolicy:
    def test_register_and_get(self) -> None:
        e = RetentionEngine()
        e.register(RetentionPolicy(data_type="audit", retention_days=2555))
        assert e.get("audit") is not None

    def test_register_overwrite(self) -> None:
        e = RetentionEngine()
        p1 = RetentionPolicy(data_type="x", retention_days=10)
        p2 = RetentionPolicy(data_type="x", retention_days=20)
        e.register(p1)
        e.register(p2)
        assert e.get("x").retention_days == 20

    def test_get_missing(self) -> None:
        e = RetentionEngine()
        assert e.get("missing") is None


class TestEvaluateNoPolicy:
    def test_unknown_type_returns_keep(self) -> None:
        e = RetentionEngine()
        verdict = e.evaluate("unknown", age_days=1000)
        assert verdict.action == RetentionAction.KEEP
        assert "no policy" in verdict.reason


class TestEvaluateRetention:
    def test_within_window(self) -> None:
        e = RetentionEngine()
        e.register(RetentionPolicy(data_type="session", retention_days=1))
        verdict = e.evaluate("session", age_days=0.5)
        assert verdict.action == RetentionAction.KEEP

    def test_at_boundary(self) -> None:
        e = RetentionEngine()
        e.register(RetentionPolicy(data_type="session", retention_days=1))
        verdict = e.evaluate("session", age_days=1.0)
        assert verdict.action == RetentionAction.KEEP

    def test_past_window_delete(self) -> None:
        e = RetentionEngine()
        e.register(
            RetentionPolicy(
                data_type="session", retention_days=1, action=RetentionAction.DELETE
            )
        )
        verdict = e.evaluate("session", age_days=2)
        assert verdict.action == RetentionAction.DELETE

    def test_past_window_archive(self) -> None:
        e = RetentionEngine()
        e.register(
            RetentionPolicy(
                data_type="audit", retention_days=2555, action=RetentionAction.ARCHIVE
            )
        )
        verdict = e.evaluate("audit", age_days=3000)
        assert verdict.action == RetentionAction.ARCHIVE


class TestEvaluateLegalHold:
    def test_hold_blocks_delete(self) -> None:
        e = RetentionEngine()
        e.register(
            RetentionPolicy(
                data_type="audit", retention_days=2555, action=RetentionAction.DELETE
            )
        )
        e.add_hold(
            LegalHold(
                data_type="audit",
                reason="investigation",
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        verdict = e.evaluate("audit", age_days=3000)
        assert verdict.action == RetentionAction.KEEP
        assert verdict.blocked_by_hold is True

    def test_hold_with_expiry_in_past(self) -> None:
        e = RetentionEngine()
        e.register(
            RetentionPolicy(
                data_type="audit", retention_days=2555, action=RetentionAction.DELETE
            )
        )
        # Hold expired 1 day ago.
        expired = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        e.add_hold(
            LegalHold(
                data_type="audit",
                reason="r",
                created_at="2024-01-01T00:00:00",
                expires_at=expired,
            )
        )
        verdict = e.evaluate("audit", age_days=3000)
        # Hold expired → delete applies.
        assert verdict.action == RetentionAction.DELETE
        assert verdict.blocked_by_hold is False

    def test_hold_active_for_different_type(self) -> None:
        e = RetentionEngine()
        e.register(
            RetentionPolicy(
                data_type="audit", retention_days=1, action=RetentionAction.DELETE
            )
        )
        e.add_hold(
            LegalHold(
                data_type="OTHER", reason="r", created_at=datetime.now(UTC).isoformat()
            )
        )
        # Hold is for OTHER, not audit.
        verdict = e.evaluate("audit", age_days=10)
        assert verdict.action == RetentionAction.DELETE
        assert verdict.blocked_by_hold is False


class TestLegalHoldManagement:
    def test_add_hold(self) -> None:
        e = RetentionEngine()
        e.add_hold(LegalHold(data_type="x", reason="r", created_at="2026"))
        assert len(e.list_holds()) == 1

    def test_remove_hold(self) -> None:
        e = RetentionEngine()
        e.add_hold(LegalHold(data_type="x", reason="r1", created_at="2026"))
        e.add_hold(LegalHold(data_type="x", reason="r2", created_at="2026"))
        e.add_hold(LegalHold(data_type="y", reason="r1", created_at="2026"))
        count = e.remove_hold("x", "r1")
        assert count == 1
        remaining = e.list_holds()
        assert len(remaining) == 2

    def test_holds_for_type(self) -> None:
        e = RetentionEngine()
        e.add_hold(LegalHold(data_type="x", reason="r1", created_at="2026"))
        e.add_hold(LegalHold(data_type="y", reason="r1", created_at="2026"))
        assert len(e.holds_for_type("x")) == 1
        assert len(e.holds_for_type("z")) == 0

    def test_has_active_hold(self) -> None:
        e = RetentionEngine()
        e.add_hold(
            LegalHold(
                data_type="x", reason="r", created_at=datetime.now(UTC).isoformat()
            )
        )
        assert e.has_active_hold("x") is True
        assert e.has_active_hold("y") is False


class TestApplyToRecord:
    def test_anonymize_removes_fields(self) -> None:
        e = RetentionEngine()
        e.register(
            RetentionPolicy(
                data_type="user",
                retention_days=365,
                action=RetentionAction.ANONYMIZE,
                anonymize_fields=("email", "phone"),
            )
        )
        record = {"id": 1, "email": "alice@x.com", "phone": "+1234"}
        verdict = e.apply_to_record(record, "user", created_at=_days_ago(400))
        assert verdict.action == RetentionAction.ANONYMIZE
        assert record["email"] == "[REDACTED]"
        assert record["phone"] == "[REDACTED]"
        assert record["id"] == 1  # non-PII preserved

    def test_archive_adds_metadata(self) -> None:
        e = RetentionEngine()
        e.register(
            RetentionPolicy(
                data_type="audit", retention_days=2555, action=RetentionAction.ARCHIVE
            )
        )
        record = {"id": 1, "data": "x"}
        verdict = e.apply_to_record(record, "audit", created_at=_days_ago(3000))
        assert verdict.action == RetentionAction.ARCHIVE
        assert "_archived_at" in record

    def test_delete_does_not_mutate(self) -> None:
        e = RetentionEngine()
        e.register(
            RetentionPolicy(
                data_type="session", retention_days=1, action=RetentionAction.DELETE
            )
        )
        record = {"id": 1, "token": "abc"}
        verdict = e.apply_to_record(record, "session", created_at=_days_ago(2))
        # Record unchanged (caller responsible for delete).
        assert verdict.action == RetentionAction.DELETE
        assert record["id"] == 1
        assert "_archived_at" not in record

    def test_keep_no_mutation(self) -> None:
        e = RetentionEngine()
        e.register(RetentionPolicy(data_type="x", retention_days=10))
        record = {"id": 1, "data": "x"}
        verdict = e.apply_to_record(record, "x", created_at=_days_ago(1))
        assert verdict.action == RetentionAction.KEEP
        assert record == {"id": 1, "data": "x"}


class TestSingleton:
    def test_singleton(self) -> None:
        e1 = get_retention_engine()
        e2 = get_retention_engine()
        assert e1 is e2

    def test_reset(self) -> None:
        e1 = get_retention_engine()
        reset_retention_engine()
        e2 = get_retention_engine()
        assert e1 is not e2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import retention_policy

        assert len(retention_policy.__all__) == 6


class TestRealisticExample:
    """Realistic: bank with audit_log (7y archive) + session (1d delete)."""

    def test_bank_retention_policy(self) -> None:
        engine = get_retention_engine()
        # Audit log: 7 years archive (regulatory).
        engine.register(
            RetentionPolicy(
                data_type="audit_log",
                retention_days=2555,
                action=RetentionAction.ARCHIVE,
            )
        )
        # Session token: 1 day delete.
        engine.register(
            RetentionPolicy(
                data_type="session_token",
                retention_days=1,
                action=RetentionAction.DELETE,
            )
        )
        # User PII: 1 year anonymize (GDPR).
        engine.register(
            RetentionPolicy(
                data_type="user_pii",
                retention_days=365,
                action=RetentionAction.ANONYMIZE,
                anonymize_fields=("email", "phone", "ssn"),
            )
        )

        # Within retention → keep.
        v1 = engine.evaluate("audit_log", age_days=100)
        assert v1.action == RetentionAction.KEEP
        v2 = engine.evaluate("session_token", age_days=0.1)
        assert v2.action == RetentionAction.KEEP

        # Past retention → policy action.
        v3 = engine.evaluate("audit_log", age_days=3000)
        assert v3.action == RetentionAction.ARCHIVE
        v4 = engine.evaluate("session_token", age_days=2)
        assert v4.action == RetentionAction.DELETE
        v5 = engine.evaluate("user_pii", age_days=400)
        assert v5.action == RetentionAction.ANONYMIZE

        # Legal hold blocks delete.
        engine.add_hold(
            LegalHold(
                data_type="session_token",
                reason="fraud-investigation",
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        v6 = engine.evaluate("session_token", age_days=10)
        assert v6.action == RetentionAction.KEEP
        assert v6.blocked_by_hold is True
