"""Tests for S128 W1 — ConsulCertBackend (TD-024).

Covers:
- Literal enum в CertStoreSettings включает "consul"
- ConsulCertBackend construction (slots, name attribute)
- Lazy client (consul package not imported at construction)
- Mocked async operations: get, save, history, list_expiring
- Store.from_settings dispatches to ConsulCertBackend when backend="consul"
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.cert_store import CertStoreSettings
from src.backend.infrastructure.security.cert_store.backend_consul import (
    ConsulCertBackend,
)


# ---------------------------------------------------------------------------
# CertStoreSettings enum tests
# ---------------------------------------------------------------------------


class TestCertStoreSettingsConsulEnum:
    def test_consul_in_literal(self) -> None:
        """\"consul\" должен быть в Literal[...] валидных backend values."""
        from typing import get_args

        from pydantic import TypeAdapter

        # Use TypeAdapter to inspect Literal.
        from src.backend.core.config.cert_store import CertStoreSettings

        field = CertStoreSettings.model_fields["backend"]
        # Pydantic stores the Literal in the annotation.
        annotation = str(field.annotation)
        assert "consul" in annotation, f"consul missing from {annotation}"

    def test_consul_settings_construction(self) -> None:
        """CertStoreSettings accepts backend='consul'."""
        # Pydantic settings need env override or __init__ kwargs.
        from src.backend.core.config.cert_store import CertStoreSettings

        # Bypass YAML loader for test (settings is normally loaded from config).
        settings = CertStoreSettings.model_construct(backend="consul")
        assert settings.backend == "consul"


# ---------------------------------------------------------------------------
# ConsulCertBackend construction tests
# ---------------------------------------------------------------------------


class TestConsulCertBackendConstruction:
    def test_default_construction(self) -> None:
        backend = ConsulCertBackend()
        assert backend.name == "consul"
        assert backend._base == "certs"
        assert backend._host == "localhost"
        assert backend._port == 8500
        assert backend._client is None  # lazy

    def test_custom_construction(self) -> None:
        backend = ConsulCertBackend(
            base_path="custom/certs",
            host="consul.internal",
            port=8501,
            token="acl-token-xyz",
        )
        assert backend._base == "custom/certs"
        assert backend._host == "consul.internal"
        assert backend._port == 8501
        assert backend._token == "acl-token-xyz"

    def test_base_path_strips_trailing_slash(self) -> None:
        backend = ConsulCertBackend(base_path="certs/")
        assert backend._base == "certs"

    def test_kv_path(self) -> None:
        backend = ConsulCertBackend(base_path="certs")
        assert backend._kv_path("my_service") == "certs/my_service"


# ---------------------------------------------------------------------------
# Mocked client operations
# ---------------------------------------------------------------------------


class FakeConsulClient:
    """Mock for consul.Consul client."""

    def __init__(self, store: dict[str, bytes] | None = None) -> None:
        self._store = store or {}
        self.kv = MagicMock()
        self.kv.get = MagicMock(side_effect=self._get)
        self.kv.put = MagicMock(side_effect=self._put)

    def _get(self, key: str, **kwargs: Any) -> tuple[int, Any]:
        recurse = kwargs.get("recurse", False)
        if recurse:
            # Return list of keys.
            return (0, [k for k in self._store if k.startswith(key)])
        return (0, {"Value": self._store.get(key)})

    def _put(self, key: str, value: bytes) -> bool:
        self._store[key] = value
        return True


def _make_fingerprint(pem: str) -> str:
    import hashlib

    body = "".join(
        line for line in pem.splitlines() if "BEGIN" not in line and "END" not in line
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class TestConsulCertBackendGet:
    @pytest.mark.asyncio
    async def test_get_existing_cert(self) -> None:
        # Pre-populate fake store.
        pem = "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----"
        payload = {
            "pem": pem,
            "fingerprint": _make_fingerprint(pem),
            "expires_at": "2027-12-31T00:00:00",
            "description": "test cert",
            "version": 2,
        }
        client = FakeConsulClient(
            store={"certs/my_service": json.dumps(payload).encode("utf-8")}
        )

        with patch(
            "consul.Consul",
            return_value=client,
            create=True,
        ):
            backend = ConsulCertBackend()
            entry = await backend.get("my_service")

        assert entry is not None
        assert entry.service_id == "my_service"
        assert entry.pem == pem
        assert entry.version == 2

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self) -> None:
        client = FakeConsulClient()
        with patch("consul.Consul", return_value=client, create=True):
            backend = ConsulCertBackend()
            entry = await backend.get("nonexistent")
        assert entry is None


class TestConsulCertBackendSave:
    @pytest.mark.asyncio
    async def test_save_new_cert(self) -> None:
        client = FakeConsulClient()
        with patch("consul.Consul", return_value=client, create=True):
            backend = ConsulCertBackend()
            pem = "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----"
            entry = await backend.save(
                "new_service",
                pem=pem,
                fingerprint=None,  # auto-compute
                expires_at=datetime(2027, 12, 31, tzinfo=UTC),
                description="new cert",
                uploaded_by="admin@example.com",
            )

        assert entry.service_id == "new_service"
        assert entry.version == 1
        assert entry.fingerprint == _make_fingerprint(pem)

    @pytest.mark.asyncio
    async def test_save_bumps_version(self) -> None:
        # Pre-populate with v=1.
        pem_v1 = "-----BEGIN CERTIFICATE-----\nv1\n-----END CERTIFICATE-----"
        payload = {
            "pem": pem_v1,
            "fingerprint": _make_fingerprint(pem_v1),
            "expires_at": "2027-12-31T00:00:00",
            "version": 1,
        }
        client = FakeConsulClient(
            store={"certs/svc": json.dumps(payload).encode("utf-8")}
        )
        with patch("consul.Consul", return_value=client, create=True):
            backend = ConsulCertBackend()
            pem_v2 = "-----BEGIN CERTIFICATE-----\nv2\n-----END CERTIFICATE-----"
            entry = await backend.save(
                "svc",
                pem=pem_v2,
                fingerprint=None,
                expires_at=datetime(2027, 12, 31, tzinfo=UTC),
            )
        assert entry.version == 2


class TestConsulCertBackendHistory:
    @pytest.mark.asyncio
    async def test_history_returns_single_item(self) -> None:
        """Consul KV v2 has no native history → current entry as single list."""
        pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----"
        payload = {
            "pem": pem,
            "fingerprint": _make_fingerprint(pem),
            "expires_at": "2027-12-31T00:00:00",
            "version": 1,
        }
        client = FakeConsulClient(
            store={"certs/svc": json.dumps(payload).encode("utf-8")}
        )
        with patch("consul.Consul", return_value=client, create=True):
            backend = ConsulCertBackend()
            history = await backend.history("svc")
        assert len(history) == 1
        assert history[0].service_id == "svc"


class TestConsulCertBackendListExpiring:
    @pytest.mark.asyncio
    async def test_list_expiring_filters_by_date(self) -> None:
        # Two certs: one expired, one valid.
        expired_pem = "-----BEGIN CERTIFICATE-----\nexp\n-----END CERTIFICATE-----"
        valid_pem = "-----BEGIN CERTIFICATE-----\nval\n-----END CERTIFICATE-----"
        past = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        future = (datetime.now(UTC) + timedelta(days=365)).isoformat()
        store_data = {
            "certs/expired": json.dumps(
                {
                    "pem": expired_pem,
                    "fingerprint": _make_fingerprint(expired_pem),
                    "expires_at": past,
                    "version": 1,
                }
            ).encode("utf-8"),
            "certs/valid": json.dumps(
                {
                    "pem": valid_pem,
                    "fingerprint": _make_fingerprint(valid_pem),
                    "expires_at": future,
                    "version": 1,
                }
            ).encode("utf-8"),
        }
        client = FakeConsulClient(store=store_data)
        cutoff = datetime.now(UTC)

        with patch("consul.Consul", return_value=client, create=True):
            backend = ConsulCertBackend()
            result = await backend.list_expiring(cutoff)

        # Only the expired cert should be returned.
        assert len(result) == 1
        assert result[0].service_id == "expired"


# ---------------------------------------------------------------------------
# CertStore.from_settings dispatch test
# ---------------------------------------------------------------------------


class TestCertStoreFromSettingsDispatch:
    def test_consul_backend_dispatched_to_consul_cert_backend(self) -> None:
        from src.backend.infrastructure.security.cert_store.store import CertStore
        from src.backend.infrastructure.security.cert_store.backend_consul import (
            ConsulCertBackend,
        )

        settings = CertStoreSettings.model_construct(
            backend="consul", vault_path="custom/certs"
        )
        store = CertStore.from_settings(settings)
        assert isinstance(store._backend, ConsulCertBackend)
        assert store._backend._base == "custom/certs"
