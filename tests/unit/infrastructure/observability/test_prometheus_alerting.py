"""TDD: Prometheus alert integration (S171 M26-P0-3, D285).

Pattern (D285, Ponytail): thin wrapper над prometheus_client.
Все алерты в одном месте для observability.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestPrometheusAlertManager:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        assert mgr is not None

    def test_default_alerts_registry(self) -> None:
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        # Default alerts: cert_expired, cert_rotation_failed, sse_stream_error
        assert "cert_expired_total" in mgr._alerts
        assert "cert_rotation_failures_total" in mgr._alerts
        # sse_stream_errors не обязателен — может быть в другой подсистеме
        # Но cert_expired total обязателен (D285)
        cert_alert = mgr._alerts["cert_expired_total"]
        assert cert_alert["condition"] == "cert_expired_total > 0"
        assert cert_alert["severity"] == "warning"

    def test_render_yaml(self) -> None:
        """render_rules_yaml() возвращает валидный Prometheus alert rules."""
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        yaml_str = mgr.render_rules_yaml()
        assert "groups:" in yaml_str
        assert "cert_expired_total" in yaml_str
        assert "alert:" in yaml_str
        assert "expr:" in yaml_str

    def test_custom_alert(self) -> None:
        """register_alert() добавляет кастомный алерт."""
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        mgr.register_alert(
            "my_custom_total",
            condition="my_custom_total > 100",
            severity="critical",
            summary="High custom metric",
            description="Custom metric exceeded threshold",
        )
        assert "my_custom_total" in mgr._alerts
        alert = mgr._alerts["my_custom_total"]
        assert alert["severity"] == "critical"
        assert alert["summary"] == "High custom metric"

    def test_unregister(self) -> None:
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        assert "cert_expired_total" in mgr._alerts
        mgr.unregister_alert("cert_expired_total")
        assert "cert_expired_total" not in mgr._alerts

    def test_to_yaml_includes_all_alerts(self) -> None:
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        mgr.register_alert(
            "test_alert", condition="test > 5", severity="info",
            summary="t", description="d"
        )
        yaml_str = mgr.render_rules_yaml()
        assert "test_alert" in yaml_str
