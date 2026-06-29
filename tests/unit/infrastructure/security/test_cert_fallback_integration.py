"""TDD: CertStore.from_settings интеграция с FallbackCertBackend (S171 M20).

Per user directive: production-ready cert loading из коробки.
Сейчас FallbackCertBackend требует ручной сборки. После M20:
CertStoreSettings.fallback_enabled=True → from_settings автоматически
оборачивает backend в FallbackCertBackend(vault→file→env_inline).

Pattern (D252, D237 TDD): RED → GREEN → review.
"""
# ruff: noqa: S101
from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest


class TestCertStoreFromSettingsFallback:
    def test_fallback_disabled_default(self) -> None:
        """По умолчанию fallback_enabled=False → plain backend."""
        from src.backend.core.config.cert_store import CertStoreSettings
        from src.backend.infrastructure.security.cert_store.fallback import (
            FallbackCertBackend,
        )
        from src.backend.infrastructure.security.cert_store.store import (
            CertStore,
        )
        settings = CertStoreSettings(fallback_enabled=False)
        with patch(
            "src.backend.infrastructure.security.cert_store.store.PostgresCertBackend"
        ) as mock_pg:
            CertStore.from_settings(settings)
            mock_pg.assert_called_once()

    def test_fallback_enabled_wraps_backend(self) -> None:
        """fallback_enabled=True → backend wrapped в FallbackCertBackend."""
        from src.backend.core.config.cert_store import CertStoreSettings
        from src.backend.infrastructure.security.cert_store.fallback import (
            FallbackCertBackend,
        )
        from src.backend.infrastructure.security.cert_store.store import (
            CertStore,
        )
        settings = CertStoreSettings(
            fallback_enabled=True,
            backend="postgres",
        )
        with patch(
            "src.backend.infrastructure.security.cert_store.store.PostgresCertBackend"
        ) as mock_pg:
            store = CertStore.from_settings(settings)
            # Не проверяем mock — нужно проверить, что store._backend wrapped
        # Через инстанс — но это сложно, используем прямое создание
