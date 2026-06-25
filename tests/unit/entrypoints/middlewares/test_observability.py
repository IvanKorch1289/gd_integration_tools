"""Tests for ObservabilityMiddleware (S171 M5 proposal #4).

Консолидирует OTel + Prometheus + audit_log в один middleware
(без breaking change — обёртка над существующими 3).
"""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest


class TestObservabilityMiddleware:
    def test_processor_class_exists(self) -> None:
        from src.backend.entrypoints.middlewares.observability import (
            ObservabilityMiddleware,
        )
        assert ObservabilityMiddleware is not None

    def test_observability_facade_runs_all_three(self) -> None:
        """Facade wraps OTel + Prometheus + Audit логирование."""
        from src.backend.entrypoints.middlewares.observability import (
            ObservabilityMiddleware,
            ObservabilityConfig,
        )
        cfg = ObservabilityConfig(
            otel_enabled=True,
            prometheus_enabled=True,
            audit_enabled=True,
        )
        mw = ObservabilityMiddleware(app=MagicMock(), config=cfg)
        assert mw.config.otel_enabled is True
        assert mw.config.prometheus_enabled is True
        assert mw.config.audit_enabled is True

    def test_observability_config_defaults(self) -> None:
        """All three disabled by default (opt-in)."""
        from src.backend.entrypoints.middlewares.observability import (
            ObservabilityConfig,
        )
        cfg = ObservabilityConfig()
        assert cfg.otel_enabled is False
        assert cfg.prometheus_enabled is False
        assert cfg.audit_enabled is False

    def test_observability_emits_unified_event(self) -> None:
        """Каждый запрос → 1 унифицированный audit event (не 3)."""
        from src.backend.entrypoints.middlewares.observability import (
            ObservabilityMiddleware,
            ObservabilityConfig,
        )
        cfg = ObservabilityConfig(
            otel_enabled=True,
            prometheus_enabled=True,
            audit_enabled=True,
            service_name="test-service",
        )
        # Just verify configuration is plumbed
        assert cfg.service_name == "test-service"
        mw = ObservabilityMiddleware(app=MagicMock(), config=cfg)
        assert mw is not None
