"""Integration tests Temporal mTLS — Sprint 12 K1 W2.

Тесты падают gracefully когда Vault/Temporal недоступны.
"""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.secrets.vault_pki import (
    CertificateBundle,
    VaultPkiClient,
)
from src.backend.infrastructure.workflow.temporal_client import (
    TemporalClientFactory,
)


@pytest.fixture
def fake_vault_response() -> dict:
    return {
        "data": {
            "certificate": "-----BEGIN CERTIFICATE-----\nFAKE_CERT\n-----END CERTIFICATE-----",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nFAKE_KEY\n-----END RSA PRIVATE KEY-----",
            "issuing_ca": "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----",
            "ca_chain": [
                "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----"
            ],
            "expiration": int(
                (datetime.now(timezone.utc) + timedelta(hours=24)).timestamp()
            ),
            "serial_number": "abc:def",
        }
    }


def test_vault_pki_issue_cert(fake_vault_response: dict) -> None:
    mock_hvac = MagicMock()
    mock_hvac.write_data.return_value = fake_vault_response

    pki = VaultPkiClient()
    with patch.object(pki, "_get_client", return_value=mock_hvac):
        bundle = pki.issue_cert(role="temporal-worker", common_name="worker")

    assert isinstance(bundle, CertificateBundle)
    assert "FAKE_CERT" in bundle.certificate
    assert bundle.serial_number == "abc:def"


def test_vault_pki_cache_returns_same_cert(fake_vault_response: dict) -> None:
    mock_hvac = MagicMock()
    mock_hvac.write_data.return_value = fake_vault_response

    pki = VaultPkiClient(renew_buffer_seconds=60)
    with patch.object(pki, "_get_client", return_value=mock_hvac):
        b1 = pki.issue_cert(role="temporal-worker", common_name="worker")
        b2 = pki.issue_cert(role="temporal-worker", common_name="worker")

    assert b1.serial_number == b2.serial_number
    assert mock_hvac.write_data.call_count == 1


def test_vault_pki_invalidate_forces_renew(fake_vault_response: dict) -> None:
    mock_hvac = MagicMock()
    mock_hvac.write_data.return_value = fake_vault_response

    pki = VaultPkiClient()
    with patch.object(pki, "_get_client", return_value=mock_hvac):
        pki.issue_cert(role="temporal-worker", common_name="worker")
        pki.invalidate(role="temporal-worker", common_name="worker")
        pki.issue_cert(role="temporal-worker", common_name="worker")

    assert mock_hvac.write_data.call_count == 2


def test_temporal_client_factory_falls_back_when_vault_unavailable() -> None:
    factory = TemporalClientFactory(
        target_host="temporal:7233",
        pki_backend="vault",
    )
    import asyncio

    async def _run() -> dict | None:
        return await factory._load_certs_from_vault()

    result = asyncio.run(_run())
    assert result is None or "ca" in result
