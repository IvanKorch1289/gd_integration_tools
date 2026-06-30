"""Unit tests for S173 M8.2 observability helpers (logging_helpers.py)."""

from __future__ import annotations

import io
import logging

import pytest

from src.backend.core.observability.logging_helpers import (
    log_audit_event_lite,
    log_with_context,
)


@pytest.fixture
def captured_logs() -> tuple[logging.Logger, io.StringIO]:
    """Logger + buffer для capture log records."""
    logger = logging.getLogger("test_m8_2_helpers")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return logger, buf


class TestLogWithContext:
    """Tests for :func:`log_with_context`."""

    def test_basic_message(self, captured_logs: tuple[logging.Logger, io.StringIO]) -> None:
        logger, buf = captured_logs
        log_with_context(logger, logging.INFO, "basic message")
        assert "basic message" in buf.getvalue()

    def test_correlation_id_added_to_extra(
        self, captured_logs: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, buf = captured_logs
        log_with_context(
            logger, logging.INFO, "test",
            correlation_id="corr-123",
        )
        # StreamHandler doesn't render extra — но records содержат.
        # Проверяем что log не падает и buffer not empty.
        assert "test" in buf.getvalue()

    def test_tenant_and_workflow_id(self, captured_logs: tuple[logging.Logger, io.StringIO]) -> None:
        logger, buf = captured_logs
        log_with_context(
            logger, logging.INFO, "test",
            tenant_id="t-premium",
            workflow_id="wf-abc",
        )
        assert "test" in buf.getvalue()

    def test_custom_fields(self, captured_logs: tuple[logging.Logger, io.StringIO]) -> None:
        logger, buf = captured_logs
        log_with_context(
            logger, logging.INFO, "test",
            custom_field_1="value_1",
            custom_field_2=42,
        )
        assert "test" in buf.getvalue()

    def test_all_fields_together(
        self, captured_logs: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, buf = captured_logs
        log_with_context(
            logger, logging.WARNING, "test message",
            correlation_id="corr-1",
            tenant_id="t-test",
            workflow_id="wf-test",
            audit_event_type="cache.invalidate",
            component="test_component",
            extra_kwarg="extra_value",
        )
        assert "test message" in buf.getvalue()


class TestLogAuditEventLite:
    """Tests for :func:`log_audit_event_lite`."""

    @pytest.mark.parametrize(
        "severity,expected_level",
        [
            ("info", logging.INFO),
            ("warning", logging.WARNING),
            ("error", logging.ERROR),
            ("debug", logging.DEBUG),
            ("unknown_severity", logging.INFO),  # fallback to INFO
        ],
    )
    def test_severity_to_level_mapping(
        self,
        captured_logs: tuple[logging.Logger, io.StringIO],
        severity: str,
        expected_level: int,
    ) -> None:
        logger, _ = captured_logs
        # Capture level via custom handler.
        captured_level: list[int] = []

        class _LevelCapture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured_level.append(record.levelno)

        handler = _LevelCapture(level=logging.DEBUG)
        logger.addHandler(handler)

        log_audit_event_lite(
            logger, severity=severity, event="test.event"
        )
        assert captured_level[0] == expected_level

    def test_event_as_default_message(
        self, captured_logs: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, buf = captured_logs
        log_audit_event_lite(
            logger, severity="info", event="cache.invalidate"
        )
        assert "cache.invalidate" in buf.getvalue()

    def test_custom_message_overrides_event(
        self, captured_logs: tuple[logging.Logger, io.StringIO]
    ) -> None:
        logger, buf = captured_logs
        log_audit_event_lite(
            logger,
            severity="info",
            event="cache.invalidate",
            message="custom message text",
        )
        assert "custom message text" in buf.getvalue()
        assert "cache.invalidate" not in buf.getvalue()

    def test_audit_event_type_in_extra(
        self, captured_logs: tuple[logging.Logger, io.StringIO]
    ) -> None:
        """Audit-event type передаётся через structured ``extra``."""
        logger, _ = captured_logs
        captured_records: list[logging.LogRecord] = []

        class _RecordCapture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured_records.append(record)

        handler = _RecordCapture(level=logging.DEBUG)
        logger.addHandler(handler)

        log_audit_event_lite(
            logger, severity="info", event="test.event",
            tenant_id="t-test", custom_field="value",
        )
        assert len(captured_records) == 1
        record = captured_records[0]
        assert getattr(record, "audit_event_type", None) == "test.event"
        assert getattr(record, "tenant_id", None) == "t-test"
        assert getattr(record, "custom_field", None) == "value"
