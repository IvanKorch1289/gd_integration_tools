"""Tests for infrastructure.observability public API."""

from __future__ import annotations

import importlib

import pytest

import src.backend.infrastructure.observability as observability_module


@pytest.mark.unit
class TestObservabilityPublicApi:
    def test_all_exports(self) -> None:
        mod = importlib.reload(observability_module)
        assert set(mod.__all__) == {
            "get_correlation_id",
            "new_correlation_id",
            "redact_for_observability",
            "set_correlation_context",
        }

    def test_re_exports_are_callable(self) -> None:
        mod = importlib.reload(observability_module)
        assert callable(mod.get_correlation_id)
        assert callable(mod.new_correlation_id)
        assert callable(mod.redact_for_observability)
        assert callable(mod.set_correlation_context)
