"""PrometheusAlertManager (S171 M26-P0-3, D285).

Единый реестр Prometheus alert rules для observability.
Включает D259 cert_expired + cert_rotation_failures (D274).

Pattern (D285, Ponytail): thin wrapper над yaml.
"""
# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("infrastructure.observability.prometheus_alerting")

__all__ = ("PrometheusAlertManager",)


class PrometheusAlertManager:
    """Реестр Prometheus alert rules.

    Usage::

        mgr = PrometheusAlertManager()
        mgr.register_alert("my_metric", condition="my > 100", severity="critical", ...)
        yaml_rules = mgr.render_rules_yaml()
        # Деплой в Prometheus:
        # curl -X POST --data-binary @rules.yaml http://prometheus/api/v1/rules
    """

    DEFAULT_ALERTS: dict[str, dict[str, str]] = {
        "cert_expired_total": {
            "condition": "cert_expired_total > 0",
            "severity": "warning",
            "summary": "TLS certificates expired (S171 M16 D245)",
            "description": "One or more TLS certificates have expired and need immediate rotation. Check cert_watcher status via /admin/certs/expiring.",
        },
        "cert_rotation_failures_total": {
            "condition": "cert_rotation_failures_total > 0",
            "severity": "critical",
            "summary": "Certificate rotation failures (S171 M24 D274)",
            "description": "Auto-rotation of expired certificates is failing. Check CertRotationWatcher logs.",
        },
    }

    def __init__(self) -> None:
        self._alerts: dict[str, dict[str, str]] = {}
        # Регистрация default alerts
        for name, config in self.DEFAULT_ALERTS.items():
            self._alerts[name] = dict(config)

    def register_alert(
        self,
        name: str,
        *,
        condition: str,
        severity: str = "warning",
        summary: str = "",
        description: str = "",
    ) -> None:
        """Регистрация кастомного alert."""
        if not name:
            raise ValueError("name обязательно")
        if not condition:
            raise ValueError("condition обязательно")
        self._alerts[name] = {
            "condition": condition,
            "severity": severity,
            "summary": summary,
            "description": description,
        }
        _logger.info("prometheus_alert.registered name=%s", name)

    def unregister_alert(self, name: str) -> None:
        if name in self._alerts:
            del self._alerts[name]
            _logger.info("prometheus_alert.unregistered name=%s", name)

    def list_alerts(self) -> list[str]:
        return sorted(self._alerts.keys())

    def render_rules_yaml(self) -> str:
        """Рендерит Prometheus alert rules в YAML формат.

        Структура:
            groups:
              - name: gd_integration_tools_alerts
                interval: 30s
                rules:
                  - alert: cert_expired_total
                    expr: cert_expired_total > 0
                    for: 5m
                    labels:
                      severity: warning
                    annotations:
                      summary: ...
                      description: ...
        """
        lines = ["groups:"]
        lines.append("  - name: gd_integration_tools_alerts")
        lines.append("    interval: 30s")
        lines.append("    rules:")
        for name, cfg in sorted(self._alerts.items()):
            lines.append(f"      - alert: {name}")
            lines.append(f"        expr: {cfg['condition']}")
            lines.append("        for: 5m")
            lines.append("        labels:")
            lines.append(f"          severity: {cfg['severity']}")
            lines.append("        annotations:")
            lines.append(f"          summary: {cfg['summary']}")
            lines.append(f"          description: {cfg['description']}")
        return "\n".join(lines) + "\n"
