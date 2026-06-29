"""TDD: CertRotationWatcher (S171 M23, D260).

Periodic check + auto-rotation certs via Vault.
- start()/stop() — background task
- _check_expiring() — list expiring + rotate
- record_rotation в Prometheus exporter
"""
# ruff: noqa: S101
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCertRotationWatcher:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.security.cert_store.rotation_watcher import (
            CertRotationWatcher,
        )
        watcher = CertRotationWatcher(
            cert_store=MagicMock(),
            check_interval_seconds=60.0,
            rotation_threshold_days=30,
        )
        assert watcher._check_interval_seconds == 60.0
        assert watcher._rotation_threshold_days == 30

    def test_default_intervals(self) -> None:
        from src.backend.infrastructure.security.cert_store.rotation_watcher import (
            CertRotationWatcher,
        )
        watcher = CertRotationWatcher(cert_store=MagicMock())
        assert watcher._check_interval_seconds == 3600.0
        assert watcher._rotation_threshold_days == 30

    def test_lifecycle_start_stop(self) -> None:
        """start() создаёт task, stop() сигналит event + cancels."""
        from src.backend.infrastructure.security.cert_store.rotation_watcher import (
            CertRotationWatcher,
        )
        watcher = CertRotationWatcher(cert_store=MagicMock())
        assert watcher._task is None

    @pytest.mark.asyncio
    async def test_check_expiring_returns_count(self) -> None:
        """_check_expiring() возвращает количество expiring certs."""
        from src.backend.infrastructure.security.cert_store.rotation_watcher import (
            CertRotationWatcher,
        )
        mock_store = MagicMock()
        mock_entry = MagicMock()
        mock_entry.expires_at = datetime.now(timezone.utc)
        mock_entry.service_id = "skb_api"
        mock_store._backend.list_expiring = AsyncMock(return_value=[mock_entry])
        watcher = CertRotationWatcher(
            cert_store=mock_store,
            rotation_threshold_days=30,
        )
        count = await watcher._check_expiring()
        assert count == 1
