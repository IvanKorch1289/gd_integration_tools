"""TDD: Prometheus cert_expired exporter (S171 M23, D259).

Метрики:
- cert_expired_total (counter) — всего expired certs
- cert_expiring_days (gauge) — дней до истечения (per cert_id)
- cert_last_rotation_timestamp (gauge) — когда последний cert rotated

Pattern (D259, Ponytail): thin wrapper над prometheus_client.
"""
# ruff: noqa: S101
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCertPrometheusExporter:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.security.cert_store.prometheus_exporter import (
            CertPrometheusExporter,
        )
        exporter = CertPrometheusExporter()
        assert exporter is not None

    def test_register_metrics(self) -> None:
        """Метрики регистрируются при init."""
        from src.backend.infrastructure.security.cert_store.prometheus_exporter import (
            CertPrometheusExporter,
        )
        exporter = CertPrometheusExporter()
        # Метрики должны быть доступны
        assert exporter.cert_expired_total is not None
        assert exporter.cert_expiring_days is not None

    def test_update_expiring_certs(self) -> None:
        """update() обновляет gauge values для expiring certs."""
        from src.backend.infrastructure.security.cert_store.prometheus_exporter import (
            CertPrometheusExporter,
        )
        exporter = CertPrometheusExporter()
        # Mock cert_store
        mock_store = MagicMock()
        mock_store._backend.list_expiring = AsyncMock(
            return_value=[]
        )
        # Не должно падать
        import asyncio
        asyncio.run(exporter.update(mock_store, days=30))

    def test_export_returns_text(self) -> None:
        """export() возвращает prometheus text format."""
        from src.backend.infrastructure.security.cert_store.prometheus_exporter import (
            CertPrometheusExporter,
        )
        exporter = CertPrometheusExporter()
        text = exporter.export()
        # Должен содержать наши метрики
        assert isinstance(text, str)
        # cert_expired_total и cert_expiring_days определены
        # (могут быть 0 если ещё не обновлялись)
        assert "cert_" in text
