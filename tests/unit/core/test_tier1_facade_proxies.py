"""TDD characterization для Sprint 225 Tier 1 (7 core/ → services/ re-exports).

BEFORE refactor — verify current behavior of all 7 facade modules.
"""

from __future__ import annotations

import pytest


class TestCoreServicesInitProxy:
    """core/services/__init__.py — BaseExternalAPIClient facade."""

    def test_module_imports(self) -> None:
        from src.backend.core.services import __all__

        assert "BaseExternalAPIClient" in __all__
        assert len(__all__) == 1

    def test_base_external_api_client_identity(self) -> None:
        from src.backend.core.services import BaseExternalAPIClient
        from src.backend.services.core.base_external_api import (
            BaseExternalAPIClient as _orig,
        )

        assert BaseExternalAPIClient is _orig


class TestCoreServicesBaseProxy:
    """core/services/base.py — duplicate BaseExternalAPIClient facade."""

    def test_base_external_api_client_identity_via_base(self) -> None:
        from src.backend.core.services.base import BaseExternalAPIClient
        from src.backend.services.core.base_external_api import (
            BaseExternalAPIClient as _orig,
        )

        assert BaseExternalAPIClient is _orig


class TestCoreServicesBaseServiceProxy:
    """core/services/base_service.py — BaseService facade."""

    def test_module_imports(self) -> None:
        from src.backend.core.services.base_service import __all__

        assert set(__all__) == {"BaseService", "create_service_class", "get_service_for_model"}

    def test_base_service_identity(self) -> None:
        from src.backend.core.services.base_service import BaseService
        from src.backend.services.core.base import BaseService as _orig

        assert BaseService is _orig

    def test_create_service_class_callable(self) -> None:
        from src.backend.core.services.base_service import create_service_class

        assert callable(create_service_class)

    def test_get_service_for_model_callable(self) -> None:
        from src.backend.core.services.base_service import get_service_for_model

        assert callable(get_service_for_model)


class TestCoreIoInitProxy:
    """core/io/__init__.py — get_order_indexer facade."""

    def test_module_imports(self) -> None:
        from src.backend.core.io import __all__

        assert "get_order_indexer" in __all__
        assert len(__all__) == 1

    def test_get_order_indexer_identity(self) -> None:
        from src.backend.core.io import get_order_indexer
        from src.backend.services.io.indexers import get_order_indexer as _orig

        assert get_order_indexer is _orig


class TestCoreIoIndexersProxy:
    """core/io/indexers.py — duplicate get_order_indexer facade."""

    def test_get_order_indexer_identity_via_indexers(self) -> None:
        from src.backend.core.io.indexers import get_order_indexer
        from src.backend.services.io.indexers import get_order_indexer as _orig

        assert get_order_indexer is _orig


class TestCoreAuthAdDirectoryProxy:
    """core/auth/ad_directory.py — AD auth facade."""

    def test_module_imports(self) -> None:
        from src.backend.core.auth.ad_directory import __all__

        assert set(__all__) == {"AdAuthError", "AdSearchEntry"}

    def test_ad_auth_error_identity(self) -> None:
        from src.backend.core.auth.ad_directory import AdAuthError
        from src.backend.services.auth.ad_directory_client import AdAuthError as _orig

        assert AdAuthError is _orig

    def test_ad_search_entry_identity(self) -> None:
        from src.backend.core.auth.ad_directory import AdSearchEntry
        from src.backend.services.auth.ad_directory_client import AdSearchEntry as _orig

        assert AdSearchEntry is _orig


class TestCoreIntegrationsSkbProxy:
    """core/integrations/skb.py — SKB API facade."""

    def test_module_imports(self) -> None:
        from src.backend.core.integrations.skb import __all__

        assert set(__all__) == {"APISKBService", "get_skb_service"}

    def test_api_skb_service_class_identity(self) -> None:
        from src.backend.core.integrations.skb import APISKBService
        from src.backend.services.integrations.skb import APISKBService as _orig

        assert APISKBService is _orig

    def test_get_skb_service_callable(self) -> None:
        from src.backend.core.integrations.skb import get_skb_service

        assert callable(get_skb_service)


class TestTier1UnknownAttributeRaises:
    """All Tier 1 facades should raise AttributeError on unknown symbols."""

    def test_core_services_unknown_raises(self) -> None:
        from src.backend.core import services

        with pytest.raises(AttributeError):
            _ = services.__getattr__("nonexistent_xyz")

    def test_core_services_base_unknown_raises(self) -> None:
        from src.backend.core.services import base

        with pytest.raises(AttributeError):
            _ = base.__getattr__("nonexistent_xyz")

    def test_core_services_base_service_unknown_raises(self) -> None:
        from src.backend.core.services import base_service

        with pytest.raises(AttributeError):
            _ = base_service.__getattr__("nonexistent_xyz")

    def test_core_io_unknown_raises(self) -> None:
        from src.backend.core import io

        with pytest.raises(AttributeError):
            _ = io.__getattr__("nonexistent_xyz")

    def test_core_io_indexers_unknown_raises(self) -> None:
        from src.backend.core.io import indexers

        with pytest.raises(AttributeError):
            _ = indexers.__getattr__("nonexistent_xyz")

    def test_core_auth_ad_directory_unknown_raises(self) -> None:
        from src.backend.core.auth import ad_directory

        with pytest.raises(AttributeError):
            _ = ad_directory.__getattr__("nonexistent_xyz")

    def test_core_integrations_skb_unknown_raises(self) -> None:
        from src.backend.core.integrations import skb

        with pytest.raises(AttributeError):
            _ = skb.__getattr__("nonexistent_xyz")