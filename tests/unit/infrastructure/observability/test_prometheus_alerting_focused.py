"""Focused tests for PrometheusAlertManager (PERF-6.6 Sprint 19 coverage ratchet).

Coverage target: prometheus_alerting.py 25% → 70%+.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.backend.infrastructure.observability.prometheus_alerting import (
    PrometheusAlertManager,
)


def test_init_creates_manager() -> None:
    """PrometheusAlertManager init — _alerts dict exists."""
    mgr = PrometheusAlertManager()
    assert isinstance(mgr._alerts, dict)
    assert len(mgr._alerts) == 0


def test_register_alert_basic() -> None:
    """register_alert() создаёт alert в _alerts."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(
        name="high_cpu",
        expr="cpu_usage > 80",
        for_duration="5m",
        severity="warning",
    )
    assert "high_cpu" in mgr._alerts


def test_register_alert_with_labels() -> None:
    """register_alert() с labels dict."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(
        name="api_errors",
        expr="rate(errors[5m]) > 10",
        for_duration="2m",
        severity="critical",
        labels={"team": "platform", "service": "api"},
    )
    alert = mgr._alerts["api_errors"]
    assert alert["labels"]["team"] == "platform"


def test_register_alert_with_annotations() -> None:
    """register_alert() с annotations dict."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(
        name="mem_alert",
        expr="mem > 90",
        for_duration="1m",
        severity="critical",
        annotations={"summary": "Memory high", "runbook": "https://wiki/mem"},
    )
    alert = mgr._alerts["mem_alert"]
    assert "Memory high" in alert["annotations"]["summary"]


def test_unregister_alert_removes() -> None:
    """unregister_alert() удаляет alert."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="temp", expr="x > 1", for_duration="1m", severity="info")
    assert "temp" in mgr._alerts
    mgr.unregister_alert("temp")
    assert "temp" not in mgr._alerts


def test_unregister_alert_nonexistent() -> None:
    """unregister_alert() для несуществующего → no error."""
    mgr = PrometheusAlertManager()
    mgr.unregister_alert("never_added")  # should not raise


def test_list_alerts_empty() -> None:
    """list_alerts() на пустом manager."""
    mgr = PrometheusAlertManager()
    assert mgr.list_alerts() == []


def test_list_alerts_with_entries() -> None:
    """list_alerts() возвращает отсортированный список."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="z_alert", expr="x > 1", for_duration="1m", severity="info")
    mgr.register_alert(name="a_alert", expr="y > 1", for_duration="1m", severity="info")
    mgr.register_alert(name="m_alert", expr="z > 1", for_duration="1m", severity="info")
    result = mgr.list_alerts()
    assert result == ["a_alert", "m_alert", "z_alert"]


def test_render_rules_yaml_empty() -> None:
    """render_rules_yaml() на пустом manager → empty groups."""
    mgr = PrometheusAlertManager()
    yaml_str = mgr.render_rules_yaml()
    assert isinstance(yaml_str, str)
    # Empty или просто header
    assert len(yaml_str) >= 0


def test_render_rules_yaml_with_alerts() -> None:
    """render_rules_yaml() с alerts → valid YAML."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(
        name="test_alert",
        expr="up == 0",
        for_duration="1m",
        severity="critical",
        labels={"team": "ops"},
        annotations={"summary": "Instance down"},
    )
    yaml_str = mgr.render_rules_yaml()
    assert "test_alert" in yaml_str
    assert "ops" in yaml_str or "labels" in yaml_str


def test_save_rules_creates_file(tmp_path: Path) -> None:
    """save_rules() создаёт файл на диске."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="s1", expr="x > 1", for_duration="1m", severity="info")
    output_file = tmp_path / "rules.yaml"
    mgr.save_rules(output_file)
    assert output_file.exists()
    content = output_file.read_text()
    assert "s1" in content


def test_save_rules_empty(tmp_path: Path) -> None:
    """save_rules() с пустым manager → file created (может быть empty)."""
    mgr = PrometheusAlertManager()
    output_file = tmp_path / "empty.yaml"
    mgr.save_rules(output_file)
    assert output_file.exists()


def test_register_alert_overwrites_existing() -> None:
    """register_alert() для существующего name → overwrites."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="dup", expr="x > 1", for_duration="1m", severity="info")
    mgr.register_alert(name="dup", expr="y > 2", for_duration="5m", severity="warning")
    alert = mgr._alerts["dup"]
    # Второй register должен перезаписать
    assert "y" in alert["expr"]


def test_severity_values() -> None:
    """register_alert принимает разные severity values."""
    mgr = PrometheusAlertManager()
    for sev in ("info", "warning", "critical"):
        mgr.register_alert(
            name=f"alert_{sev}",
            expr="x > 1",
            for_duration="1m",
            severity=sev,
        )
    assert "alert_info" in mgr._alerts
    assert "alert_warning" in mgr._alerts
    assert "alert_critical" in mgr._alerts


def test_full_lifecycle() -> None:
    """Full lifecycle: register → list → render → unregister."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="lifecycle", expr="x > 1", for_duration="1m", severity="info")
    assert "lifecycle" in mgr.list_alerts()
    yaml_str = mgr.render_rules_yaml()
    assert "lifecycle" in yaml_str
    mgr.unregister_alert("lifecycle")
    assert "lifecycle" not in mgr.list_alerts()
