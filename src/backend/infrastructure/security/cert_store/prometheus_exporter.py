"""Prometheus exporter для cert_store (S171 M23, D259).

Метрики для мониторинга cert_expiring через Prometheus:
- cert_expired_total (counter) — всего certs с expired (last check)
- cert_expiring_days (gauge) — дней до истечения per cert_id
- cert_last_rotation_timestamp_seconds (gauge) — когда последний раз rotated
- cert_rotation_failures_total (counter) — failed rotation attempts (D260)

Pattern (D259, Ponytail): thin wrapper над prometheus_client.
Production: /metrics endpoint exposes cert_* metrics.
"""
# ruff: noqa: E501
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.infrastructure.security.cert_store.store import (
        CertStore,
    )

logger = get_logger("security.cert_store.prometheus")

__all__ = ("CertPrometheusExporter",)


class CertPrometheusExporter:
    """Prometheus exporter для cert_store метрик (D259).

    Использование (в lifespan):
        exporter = CertPrometheusExporter()
        # Periodic update (каждые 60s, например)
        await exporter.update(cert_store, days=30)
        # В /metrics endpoint
        return exporter.export()
    """

    def __init__(self) -> None:
        try:
            from prometheus_client import (
                CollectorRegistry,
                Counter,
                Gauge,
                generate_latest,
            )
        except ImportError as exc:
            raise ImportError(
                "prometheus_client не установлен. pip install prometheus-client"
            ) from exc

        # Изолированный registry — не загрязняет global
        self._registry = CollectorRegistry()

        self.cert_expired_total = Counter(
            "cert_expired_total",
            "Total number of expired certificates at last check",
            registry=self._registry,
        )
        self.cert_expiring_days = Gauge(
            "cert_expiring_days",
            "Days remaining before certificate expiration (per cert_id)",
            ["cert_id"],
            registry=self._registry,
        )
        self.cert_last_rotation_timestamp_seconds = Gauge(
            "cert_last_rotation_timestamp_seconds",
            "Unix timestamp of last successful cert rotation",
            registry=self._registry,
        )
        self.cert_rotation_failures_total = Counter(
            "cert_rotation_failures_total",
            "Total number of failed cert rotation attempts (D260)",
            registry=self._registry,
        )
        # initialize last_rotation to 0
        self.cert_last_rotation_timestamp_seconds.set(0)

    async def update(self, store: "CertStore", *, days: int = 30) -> None:
        """Обновить метрики на основе текущего состояния cert_store.

        Args:
            store: CertStore instance.
            days: Окно в днях для проверки expiring.
        """
        now = datetime.now(timezone.utc)
        before = now.timestamp() + days * 86400

        # Получить истекающие через backend
        try:
            entries = await store._backend.list_expiring(before=before)
        except Exception as exc:
            logger.warning("cert.prometheus.list_expiring_error: %s", exc)
            return

        # Reset expiring metrics
        expired_count = 0
        for entry in entries:
            exp = getattr(entry, "expires_at", None)
            if exp is None:
                continue
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            seconds_remaining = (exp.timestamp() - now.timestamp())
            days_remaining = seconds_remaining / 86400
            sid = getattr(entry, "service_id", "unknown")
            if days_remaining <= 0:
                expired_count += 1
            self.cert_expiring_days.labels(cert_id=sid).set(days_remaining)

        self.cert_expired_total.inc(expired_count)
        logger.info(
            "cert.prometheus.update days=%d expired=%d total=%d",
            days, expired_count, len(entries),
        )

    def record_rotation(self, *, success: bool) -> None:
        """Записать факт rotation (D260).

        Args:
            success: True если rotation успешна, False если failed.
        """
        if success:
            self.cert_last_rotation_timestamp_seconds.set(time.time())
        else:
            self.cert_rotation_failures_total.inc()
        logger.info("cert.prometheus.rotation success=%s", success)

    def export(self) -> str:
        """Экспортировать метрики в prometheus text format."""
        from prometheus_client import generate_latest

        return generate_latest(self._registry).decode("utf-8")
