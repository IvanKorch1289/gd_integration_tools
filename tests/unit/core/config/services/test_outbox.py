"""Tests for OutboxSettings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.config.services.outbox import OutboxSettings


class TestOutboxSettings:
    def test_defaults(self) -> None:
        s = OutboxSettings()
        assert s.enabled is False
        assert s.poll_interval_seconds == 1.0
        assert s.batch_size == 100
        assert s.max_retries == 5
        assert s.retry_backoff_seconds == 2.0
        assert s.shutdown_timeout_seconds == 10.0

    def test_yaml_group(self) -> None:
        assert OutboxSettings.yaml_group == "outbox"

    def test_bounds_too_low(self) -> None:
        with pytest.raises(ValidationError):
            OutboxSettings(poll_interval_seconds=0.01)

    def test_bounds_too_high(self) -> None:
        with pytest.raises(ValidationError):
            OutboxSettings(batch_size=20000)

    def test_custom_values(self) -> None:
        s = OutboxSettings(
            enabled=True,
            poll_interval_seconds=5.0,
            batch_size=50,
            max_retries=3,
            retry_backoff_seconds=1.0,
            shutdown_timeout_seconds=30.0,
        )
        assert s.enabled is True
        assert s.poll_interval_seconds == 5.0
        assert s.batch_size == 50
        assert s.max_retries == 3
        assert s.retry_backoff_seconds == 1.0
        assert s.shutdown_timeout_seconds == 30.0
