"""Focused tests for ``core.dsl_lint`` (Wave 2 DX #28)."""

from __future__ import annotations

import pytest

from src.backend.core.dsl_lint import (
    DSLLinter,
    LintResult,
    LintSeverity,
    LintViolation,
    get_dsl_linter,
)
from src.backend.core.dsl_lint.linter import reset_dsl_linter


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_dsl_linter()


class TestLintSeverity:
    def test_values(self) -> None:
        assert LintSeverity.ERROR.value == "error"
        assert LintSeverity.WARNING.value == "warning"
        assert LintSeverity.INFO.value == "info"


class TestLintViolation:
    def test_init(self) -> None:
        v = LintViolation(
            rule_id="L001",
            severity=LintSeverity.ERROR,
            message="missing timeout",
        )
        assert v.line is None
        assert v.column is None


class TestLintResult:
    def test_empty(self) -> None:
        r = LintResult(route_id="r1")
        assert r.violations == []
        assert r.has_errors is False
        assert r.error_count == 0
        assert r.warning_count == 0

    def test_with_errors(self) -> None:
        r = LintResult(
            route_id="r1",
            violations=[
                LintViolation("L001", LintSeverity.ERROR, "x"),
                LintViolation("L003", LintSeverity.WARNING, "y"),
                LintViolation("L002", LintSeverity.ERROR, "z"),
            ],
        )
        assert r.has_errors is True
        assert r.error_count == 2
        assert r.warning_count == 1


class TestDSLLinterInit:
    def test_init(self) -> None:
        l = DSLLinter()
        assert l is not None


class TestLintRouteValid:
    """Valid route — no violations."""

    def test_minimal_valid(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "team-x",
            "contract": {"timeout_seconds": 30},
        }
        result = linter.lint_route(config)
        assert result.has_errors is False
        assert result.violations == []

    def test_full_valid_write_route(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "order-create",
            "owner": "team-payments",
            "source": "timer:60s|api=https://x",
            "contract": {
                "timeout_seconds": 30,
                "idempotency_key_field": "order_id",
                "dlq_topic": "events.orders.dlq",
            },
            "security": {"pii_policy": "mask"},
        }
        result = linter.lint_route(config)
        assert result.has_errors is False


class TestLintMissingOwner:
    def test_missing_owner(self) -> None:
        linter = DSLLinter()
        config = {"id": "r1", "contract": {"timeout_seconds": 30}}
        result = linter.lint_route(config)
        assert any(v.rule_id == "L007" for v in result.violations)
        assert result.has_errors is True


class TestLintMissingTimeout:
    def test_missing_timeout(self) -> None:
        linter = DSLLinter()
        config = {"id": "r1", "owner": "x"}
        result = linter.lint_route(config)
        assert any(v.rule_id == "L001" for v in result.violations)

    def test_zero_timeout(self) -> None:
        linter = DSLLinter()
        config = {"id": "r1", "owner": "x", "contract": {"timeout_seconds": 0}}
        result = linter.lint_route(config)
        assert any(v.rule_id == "L001" and "must be > 0" in v.message for v in result.violations)

    def test_negative_timeout(self) -> None:
        linter = DSLLinter()
        config = {"id": "r1", "owner": "x", "contract": {"timeout_seconds": -1}}
        result = linter.lint_route(config)
        assert any(v.rule_id == "L001" for v in result.violations)

    def test_too_large_timeout(self) -> None:
        linter = DSLLinter()
        config = {"id": "r1", "owner": "x", "contract": {"timeout_seconds": 600}}
        result = linter.lint_route(config)
        assert any(v.rule_id == "L005" for v in result.violations)


class TestLintIdempotency:
    def test_write_without_idempotency(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "x",
            "source": "timer:60s|api=https://x",
            "contract": {"timeout_seconds": 30},
        }
        result = linter.lint_route(config)
        assert any(v.rule_id == "L002" for v in result.violations)

    def test_write_with_idempotency_ok(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "x",
            "source": "timer:60s|api=https://x",
            "contract": {"timeout_seconds": 30, "idempotency_key_field": "x"},
        }
        result = linter.lint_route(config)
        assert not any(v.rule_id == "L002" for v in result.violations)

    def test_read_only_no_idempotency_required(self) -> None:
        """Read-only route (нет side effects) → L002 не срабатывает."""
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "x",
            "source": "http://api.example.com",
            "contract": {"timeout_seconds": 30},
        }
        # Without explicit write detection tags, source only "http://...".
        result = linter.lint_route(config)
        assert not any(v.rule_id == "L002" for v in result.violations)


class TestLintDLQ:
    def test_write_without_dlq_warning(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "x",
            "source": "timer:60s",
            "contract": {"timeout_seconds": 30, "idempotency_key_field": "x"},
        }
        result = linter.lint_route(config)
        assert any(v.rule_id == "L003" and v.severity == LintSeverity.WARNING for v in result.violations)

    def test_write_with_dlq_no_warning(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "x",
            "source": "timer:60s",
            "contract": {
                "timeout_seconds": 30,
                "idempotency_key_field": "x",
                "dlq_topic": "events.r1.dlq",
            },
        }
        result = linter.lint_route(config)
        assert not any(v.rule_id == "L003" for v in result.violations)


class TestLintPII:
    def test_pii_fields_without_policy_warning(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "x",
            "source": "timer:60s",
            "input_fields": ["email", "ssn"],
            "contract": {
                "timeout_seconds": 30,
                "idempotency_key_field": "x",
                "dlq_topic": "events.r1.dlq",
            },
        }
        result = linter.lint_route(config)
        assert any(v.rule_id == "L004" for v in result.violations)

    def test_pii_fields_with_policy_no_warning(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "x",
            "source": "timer:60s",
            "input_fields": ["email"],
            "contract": {
                "timeout_seconds": 30,
                "idempotency_key_field": "x",
                "dlq_topic": "events.r1.dlq",
            },
            "security": {"pii_policy": "mask"},
        }
        result = linter.lint_route(config)
        assert not any(v.rule_id == "L004" for v in result.violations)


class TestLintMaxRetries:
    def test_too_many_retries(self) -> None:
        linter = DSLLinter()
        config = {
            "id": "r1",
            "owner": "x",
            "source": "timer:60s",
            "contract": {
                "timeout_seconds": 30,
                "idempotency_key_field": "x",
                "dlq_topic": "events.r1.dlq",
                "max_retries": 20,
            },
        }
        result = linter.lint_route(config)
        assert any(v.rule_id == "L006" for v in result.violations)


class TestSideEffectsDetection:
    def test_timer_source_detects_external_call(self) -> None:
        linter = DSLLinter()
        effects = linter._detect_side_effects({"source": "timer:60s|api=x"})
        assert "external_call" in effects

    def test_filewatcher_source_detects_file_write(self) -> None:
        linter = DSLLinter()
        effects = linter._detect_side_effects({"source": "filewatcher:/tmp"})
        assert "file_write" in effects

    def test_cdc_source_detects_db_write(self) -> None:
        linter = DSLLinter()
        effects = linter._detect_side_effects({"source": "cdc:postgres/x"})
        assert "db_write" in effects

    def test_tags_detect_db(self) -> None:
        linter = DSLLinter()
        effects = linter._detect_side_effects({"tags": ["db-write"]})
        assert "db_write" in effects

    def test_tags_detect_mq(self) -> None:
        linter = DSLLinter()
        effects = linter._detect_side_effects({"tags": ["mq-publish"]})
        assert "mq_publish" in effects


class TestSensitiveFieldsDetection:
    def test_email_detected(self) -> None:
        linter = DSLLinter()
        fields = linter._detect_sensitive_fields({"input_fields": ["email"]})
        assert "email" in fields

    def test_ssn_detected(self) -> None:
        linter = DSLLinter()
        fields = linter._detect_sensitive_fields({"input_fields": ["customer_ssn"]})
        assert "customer_ssn" in fields

    def test_no_sensitive(self) -> None:
        linter = DSLLinter()
        fields = linter._detect_sensitive_fields({"input_fields": ["order_id"]})
        assert fields == []

    def test_description_keyword(self) -> None:
        linter = DSLLinter()
        fields = linter._detect_sensitive_fields({"description": "Handle passport data"})
        assert "passport" in fields


class TestSingleton:
    def test_singleton(self) -> None:
        l1 = get_dsl_linter()
        l2 = get_dsl_linter()
        assert l1 is l2

    def test_reset(self) -> None:
        l1 = get_dsl_linter()
        reset_dsl_linter()
        l2 = get_dsl_linter()
        assert l1 is not l2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import dsl_lint

        assert len(dsl_lint.__all__) == 5


class TestRealisticExample:
    def test_lint_full_order_route(self) -> None:
        """Realistic example: lint a full order route config."""
        linter = get_dsl_linter()
        config = {
            "id": "order-create",
            "owner": "team-payments",
            "source": "timer:60s|api=https://api.example.com/orders",
            "description": "Create order",
            "tags": ["db-write"],
            "input_fields": ["order_id", "amount", "customer_id"],
            "contract": {
                "timeout_seconds": 30,
                "idempotency_key_field": "order_id",
                "dlq_topic": "events.orders.dlq",
                "max_retries": 3,
            },
            "security": {
                "requires_permission": "orders.create",
                "pii_policy": "mask",
            },
        }
        result = linter.lint_route(config)
        # No errors expected.
        assert result.has_errors is False
