"""TDD: alertmanager integration (M27, D289).

Pattern (D289, Ponytail): PrometheusAlertManager интегрирован с D259 exporter
и CertRotationWatcher. CI deploy rules.
"""
# ruff: noqa: S101
from __future__ import annotations
import pytest


class TestAlertIntegration:
    def test_alerts_reference_real_metric_names(self) -> None:
        """Default alerts должны ссылаться на реальные metric names (D259)."""
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        # D259 CertPrometheusExporter метрики
        assert "cert_expired_total" in mgr._alerts
        assert "cert_rotation_failures_total" in mgr._alerts

    def test_yaml_includes_for_clause(self) -> None:
        """Каждое правило должно иметь `for` clause (D289 Prometheus best practice)."""
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        yaml = mgr.render_rules_yaml()
        # Каждое правило имеет `for: 5m`
        assert yaml.count("for: 5m") >= len(mgr._alerts)

    def test_alerts_have_severity_labels(self) -> None:
        """Severity label обязателен (warning/critical)."""
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        mgr = PrometheusAlertManager()
        yaml = mgr.render_rules_yaml()
        assert "severity: warning" in yaml
        assert "severity: critical" in yaml

    def test_yamlsave_to_file(self) -> None:
        """save_rules() записывает YAML в файл (для CI deploy)."""
        from src.backend.infrastructure.observability.prometheus_alerting import (
            PrometheusAlertManager,
        )
        from pathlib import Path
        import tempfile
        mgr = PrometheusAlertManager()
        with tempfile.TemporaryDirectory() as tmp:
            rules_path = Path(tmp) / "alert_rules.yaml"
            mgr.save_rules(rules_path)
            assert rules_path.exists()
            content = rules_path.read_text()
            assert "groups:" in content
            assert "cert_expired_total" in content
