"""Tests for CredentialProvider."""
from __future__ import annotations


import pytest

from src.backend.core.security.credential_provider import (
    CredentialProvider,
    CredentialSpec,
)


@pytest.mark.unit
def test_is_vault_detection() -> None:
    spec = CredentialSpec(name="kafka", secret_ref="vault:kv/data")
    assert spec.is_vault is True

    spec2 = CredentialSpec(name="foo", secret_ref="env:FOO")
    assert spec2.is_vault is False


@pytest.mark.unit
async def test_resolve_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_PASSWORD", "secret123")
    provider = CredentialProvider()
    provider.register_spec(CredentialSpec(name="k1", secret_ref="env:KAFKA_PASSWORD"))
    cred = await provider.get("k1")
    assert cred.value == {"value": "secret123"}


@pytest.mark.unit
async def test_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_CACHE_KEY", "v1")
    provider = CredentialProvider()
    provider.register_spec(
        CredentialSpec(name="c1", secret_ref="env:TEST_CACHE_KEY", ttl_seconds=60)
    )
    c1 = await provider.get("c1")
    c2 = await provider.get("c1")
    assert c1.resolution_id == c2.resolution_id  # cached


@pytest.mark.unit
async def test_invalidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_CACHE_KEY2", "v1")
    provider = CredentialProvider()
    provider.register_spec(CredentialSpec(name="c2", secret_ref="env:TEST_CACHE_KEY2"))
    await provider.get("c2")
    provider.invalidate("c2")
    c2 = await provider.get("c2")
    assert c2.value == {"value": "v1"}
