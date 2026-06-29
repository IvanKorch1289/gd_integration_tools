"""TDD: CertBackend registry pattern (S171 M22, D258).

Per M20 plan: extensions могут регистрировать свои CertBackend
(например, HSM-bridge, cloud-KMS, etc.) без изменения core.

Pattern (D258, Ponytail): backend_id → CertBackend class,
register/unregister/get/list, like a plugin registry.

Test: register custom backend → get returns instance.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestCertBackendRegistry:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_registry import (
            CertBackendRegistry,
        )
        reg = CertBackendRegistry()
        assert reg is not None

    def test_register_custom_backend(self) -> None:
        """register() добавляет backend по id."""
        from src.backend.infrastructure.security.cert_store.backend_registry import (
            CertBackendRegistry,
        )
        from src.backend.infrastructure.security.cert_store.backend_base import (
            CertBackend,
        )
        reg = CertBackendRegistry()

        class MyCustomBackend(CertBackend):
            async def get(self, service_id):
                return None
            async def set(self, service_id, pem):
                pass
            async def save(self, service_id, pem, expires_at, *, description=None):
                pass
            async def history(self, service_id):
                return []
            async def list_expiring(self, before):
                return []
            def list_all(self):
                return []
            async def delete(self, service_id):
                return True

        reg.register("my_custom", MyCustomBackend)
        assert "my_custom" in reg.list_ids()

    def test_get_returns_class(self) -> None:
        """get(id) возвращает CertBackend class."""
        from src.backend.infrastructure.security.cert_store.backend_registry import (
            CertBackendRegistry,
        )
        from src.backend.infrastructure.security.cert_store.backend_base import (
            CertBackend,
        )
        reg = CertBackendRegistry()

        class MyBackend(CertBackend):
            async def get(self, service_id):
                return None
            async def set(self, service_id, pem):
                pass
            async def save(self, service_id, pem, expires_at, *, description=None):
                pass
            async def history(self, service_id):
                return []
            async def list_expiring(self, before):
                return []
            def list_all(self):
                return []
            async def delete(self, service_id):
                return True

        reg.register("foo", MyBackend)
        cls = reg.get("foo")
        assert cls is MyBackend

    def test_get_unknown_raises(self) -> None:
        """get(unknown) raises KeyError."""
        from src.backend.infrastructure.security.cert_store.backend_registry import (
            CertBackendRegistry,
        )
        reg = CertBackendRegistry()
        with pytest.raises(KeyError):
            reg.get("nonexistent")

    def test_list_ids(self) -> None:
        """list_ids() возвращает все зарегистрированные id."""
        from src.backend.infrastructure.security.cert_store.backend_registry import (
            CertBackendRegistry,
        )
        from src.backend.infrastructure.security.cert_store.backend_base import (
            CertBackend,
        )
        reg = CertBackendRegistry()

        class B(CertBackend):
            async def get(self, service_id):
                return None
            async def set(self, service_id, pem):
                pass
            async def save(self, service_id, pem, expires_at, *, description=None):
                pass
            async def history(self, service_id):
                return []
            async def list_expiring(self, before):
                return []
            def list_all(self):
                return []
            async def delete(self, service_id):
                return True

        reg.register("a", B)
        reg.register("b", B)
        ids = reg.list_ids()
        assert "a" in ids
        assert "b" in ids

    def test_unregister(self) -> None:
        """unregister(id) удаляет backend."""
        from src.backend.infrastructure.security.cert_store.backend_registry import (
            CertBackendRegistry,
        )
        from src.backend.infrastructure.security.cert_store.backend_base import (
            CertBackend,
        )
        reg = CertBackendRegistry()

        class B(CertBackend):
            async def get(self, service_id):
                return None
            async def set(self, service_id, pem):
                pass
            async def save(self, service_id, pem, expires_at, *, description=None):
                pass
            async def history(self, service_id):
                return []
            async def list_expiring(self, before):
                return []
            def list_all(self):
                return []
            async def delete(self, service_id):
                return True

        reg.register("temp", B)
        assert "temp" in reg.list_ids()
        reg.unregister("temp")
        assert "temp" not in reg.list_ids()
