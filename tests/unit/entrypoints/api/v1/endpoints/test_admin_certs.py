"""TDD: list_expiring admin endpoint (S171 M21, D256).

Per M20 plan: GET /admin/certs/expiring?days=N → JSON список
с {cert_id, expires_at, days_remaining}.
Интеграция с Prometheus alert (DEFER M21+).

Pattern (D256, D237 TDD): RED → GREEN → review.
"""
# ruff: noqa: S101
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestAdminCertsExpiring:
    def test_endpoint_exists(self) -> None:
        """GET /admin/certs/expiring должен быть зарегистрирован."""
        from src.backend.entrypoints.api.v1.endpoints.admin_certs import router
        assert router is not None
        # Проверить что endpoint зарегистрирован
        paths = [r.path for r in router.routes]
        assert any("/admin/certs/expiring" in p for p in paths)

    def test_default_days_30(self) -> None:
        """По умолчанию days=30."""
        from src.backend.entrypoints.api.v1.endpoints.admin_certs import (
            EXPIRING_DEFAULT_DAYS,
        )
        assert EXPIRING_DEFAULT_DAYS == 30

    def test_response_format(self) -> None:
        """Response содержит cert_id, expires_at, days_remaining."""
        from src.backend.entrypoints.api.v1.endpoints.admin_certs import (
            CertExpiringItem,
        )
        item = CertExpiringItem(
            cert_id="skb_api",
            expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            days_remaining=200,
        )
        assert item.cert_id == "skb_api"
        assert item.days_remaining == 200
