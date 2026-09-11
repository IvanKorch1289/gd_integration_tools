"""Focused tests for PrometheusAlertManager (PERF-6.6 Sprint 19 coverage ratchet).

2026-09-11: переписаны под текущий контракт — register_alert(condition=,
summary=, description=) без labels/annotations/for_duration, init сеет
DEFAULT_ALERTS (пустым менеджер больше не бывает).
"""

from __future__ import annotations

from pathlib import Path

from src.backend.infrastructure.observability.prometheus_alerting import (
    PrometheusAlertManager,
)


def test_init_creates_manager() -> None:
    """Init — _alerts dict, засеян DEFAULT_ALERTS (не пустой)."""
    mgr = PrometheusAlertManager()
    assert isinstance(mgr._alerts, dict)
    assert len(mgr._alerts) == len(mgr.DEFAULT_ALERTS)
    assert set(mgr.list_alerts()) == set(mgr.DEFAULT_ALERTS)


def test_register_alert_basic() -> None:
    """register_alert(condition=) создаёт alert в _alerts."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(
        name="high_cpu",
        condition="cpu_usage > 80",
        severity="warning",
    )
    assert "high_cpu" in mgr._alerts
    assert mgr._alerts["high_cpu"]["condition"] == "cpu_usage > 80"


def test_register_alert_with_summary() -> None:
    """register_alert() с summary/description."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(
        name="api_errors",
        condition="rate(errors[5m]) > 10",
        severity="critical",
        summary="API error burst",
        description="Check upstream logs",
    )
    alert = mgr._alerts["api_errors"]
    assert alert["summary"] == "API error burst"
    assert alert["description"] == "Check upstream logs"


def test_register_alert_defaults() -> None:
    """register_alert() без severity/summary — значения по умолчанию."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="mem_alert", condition="mem > 90")
    alert = mgr._alerts["mem_alert"]
    assert alert["severity"] == "warning"
    assert alert["summary"] == ""


def test_unregister_alert_removes() -> None:
    """unregister_alert() удаляет alert."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="temp", condition="x > 1", severity="info")
    assert "temp" in mgr._alerts
    mgr.unregister_alert("temp")
    assert "temp" not in mgr._alerts


def test_unregister_alert_nonexistent() -> None:
    """unregister_alert() для несуществующего → no error."""
    mgr = PrometheusAlertManager()
    mgr.unregister_alert("never_added")  # should not raise


def test_list_alerts_contains_defaults_sorted() -> None:
    """list_alerts() сортирован и содержит defaults + новые."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="z_alert", condition="x > 1", severity="info")
    mgr.register_alert(name="a_alert", condition="y > 1", severity="info")
    result = mgr.list_alerts()
    assert result == sorted(result)
    assert {"a_alert", "z_alert"} <= set(result)


def test_render_rules_yaml_defaults() -> None:
    """render_rules_yaml() на дефолтном менеджере → валидный YAML с alerts."""
    mgr = PrometheusAlertManager()
    yaml_str = mgr.render_rules_yaml()
    assert isinstance(yaml_str, str)
    assert "cert_expired_total" in yaml_str


def test_render_rules_yaml_with_alerts() -> None:
    """render_rules_yaml() с кастомным alert → имя и condition в YAML."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(
        name="test_alert",
        condition="up == 0",
        severity="critical",
        summary="Instance down",
    )
    yaml_str = mgr.render_rules_yaml()
    assert "test_alert" in yaml_str
    assert "up == 0" in yaml_str


def test_save_rules_creates_file(tmp_path: Path) -> None:
    """save_rules() создаёт файл на диске."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="s1", condition="x > 1", severity="info")
    output_file = tmp_path / "rules.yaml"
    mgr.save_rules(output_file)
    assert output_file.exists()
    content = output_file.read_text()
    assert "s1" in content


def test_save_rules_empty(tmp_path: Path) -> None:
    """save_rules() пишет валидный файл (дефолтные alerts присутствуют)."""
    mgr = PrometheusAlertManager()
    output_file = tmp_path / "empty.yaml"
    mgr.save_rules(output_file)
    assert output_file.exists()


def test_register_alert_overwrites_existing() -> None:
    """register_alert() для существующего name → overwrites."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="dup", condition="x > 1", severity="info")
    mgr.register_alert(name="dup", condition="y > 2", severity="warning")
    alert = mgr._alerts["dup"]
    assert alert["condition"] == "y > 2"
    assert alert["severity"] == "warning"


def test_severity_values() -> None:
    """register_alert принимает разные severity values."""
    mgr = PrometheusAlertManager()
    for sev in ("info", "warning", "critical"):
        mgr.register_alert(
            name=f"alert_{sev}",
            condition="x > 1",
            severity=sev,
        )
    assert "alert_info" in mgr._alerts
    assert "alert_warning" in mgr._alerts
    assert "alert_critical" in mgr._alerts


def test_full_lifecycle() -> None:
    """Full lifecycle: register → list → render → unregister."""
    mgr = PrometheusAlertManager()
    mgr.register_alert(name="lifecycle", condition="x > 1", severity="info")
    assert "lifecycle" in mgr.list_alerts()
    yaml_str = mgr.render_rules_yaml()
    assert "lifecycle" in yaml_str
    mgr.unregister_alert("lifecycle")
    assert "lifecycle" not in mgr.list_alerts()
