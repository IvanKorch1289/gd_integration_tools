"""Tests for graceful_degradation module (E.5)."""

import asyncio
import pytest
from collections import deque


class TestGracefulDegradation:
    """Tests for GracefulDegradationRegistry (bug B.2 fixed)."""

    def test_window_size_respected(self):
        """DegradationFeature with window_size=50 creates deque with maxlen=50.

        Bug B.2: __post_init__ was missing so window_size was ignored.
        Fix adds __post_init__ that validates/fixes outcomes.maxlen.
        """
        from src.backend.core.resilience.graceful_degradation import (
            DegradationFeature,
            GracefulDegradationRegistry,
        )

        feature = DegradationFeature(
            name="test_feature",
            full_handler=lambda: "full",
            degraded_handler=lambda: "degraded",
            error_threshold=0.3,
            recovery_threshold=0.05,
            window_size=50,
        )

        registry = GracefulDegradationRegistry()
        registry.register(feature)

        runtime = registry._features["test_feature"]
        assert runtime.outcomes.maxlen == 50

        # Also verify that outcomes is a deque
        assert isinstance(runtime.outcomes, deque)

    def test_window_size_default(self):
        """Default window_size is 100."""
        from src.backend.core.resilience.graceful_degradation import (
            DegradationFeature,
            GracefulDegradationRegistry,
        )

        feature = DegradationFeature(
            name="default_window",
            full_handler=lambda: "full",
            degraded_handler=lambda: "degraded",
        )

        registry = GracefulDegradationRegistry()
        registry.register(feature)

        runtime = registry._features["default_window"]
        assert runtime.outcomes.maxlen == 100
