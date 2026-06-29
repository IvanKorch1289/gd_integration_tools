"""TDD: auto_rotate для CertRotationWatcher (M24 P2 #11, D274).

При days_remaining <= 0 (cert expired) И auto_rotate=True —
вызвать set() с renewal callback. По умолчанию False (D260 Ponytail YAGNI).
"""
# ruff: noqa: S101
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestAutoRotate:
    def test_default_no_auto_rotate(self) -> None:
        from src.backend.infrastructure.security.cert_store.rotation_watcher import (
            CertRotationWatcher,
        )
        watcher = CertRotationWatcher(cert_store=MagicMock())
        assert watcher._auto_rotate is False

    def test_explicit_auto_rotate(self) -> None:
        from src.backend.infrastructure.security.cert_store.rotation_watcher import (
            CertRotationWatcher,
        )
        watcher = CertRotationWatcher(cert_store=MagicMock(), auto_rotate=True)
        assert watcher._auto_rotate is True

    @pytest.mark.asyncio
    async def test_expired_cert_triggers_renewal(self) -> None:
        """days_remaining <= 0 + auto_rotate=True → вызов renewal callback."""
        from src.backend.infrastructure.security.cert_store.rotation_watcher import (
            CertRotationWatcher,
        )
        from datetime import datetime, timezone, timedelta
        mock_store = MagicMock()
        mock_entry = MagicMock()
        mock_entry.service_id = "skb_api"
        mock_entry.expires_at = datetime.now(timezone.utc) - timedelta(days=1)  # expired
        mock_store._backend.list_expiring = AsyncMock(return_value=[mock_entry])
        mock_renewal = AsyncMock()
        watcher = CertRotationWatcher(
            cert_store=mock_store,
            rotation_threshold_days=30,
            auto_rotate=True,
            renewal_callback=mock_renewal,
        )
        await watcher._check_expiring()
        # Renewal callback был вызван
        mock_renewal.assert_awaited_once()
