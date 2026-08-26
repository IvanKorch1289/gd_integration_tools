"""Tests for CredentialProvider."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.interfaces.secrets import SecretsBackend
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
async def test_resolve_vault_uses_registered_secrets_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AsyncMock(spec=SecretsBackend)
    backend.get_secret.return_value = "vault-value"
    monkeypatch.setattr(
        "src.backend.core.svcs_registry.get_service",
        lambda _contract: backend,
    )
    provider = CredentialProvider()
    provider.register_spec(CredentialSpec(name="vault", secret_ref="vault:kv/data"))

    cred = await provider.get("vault")

    assert cred.value == {"value": "vault-value"}
    backend.get_secret.assert_awaited_once_with("kv/data")


@pytest.mark.unit
async def test_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_CACHE_KEY", "v1")
    provider = CredentialProvider()
    provider.register_spec(
        CredentialSpec(name="c1", secret_ref="env:TEST_CACHE_KEY", ttl_seconds=60),
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


# ── Cycle 59 L8 regression tests ─────────────────────────────────────────


@pytest.mark.unit
async def test_get_unknown_spec_raises_keyerror() -> None:
    """Cycle 59 fix: cache-hit path no longer crashes with KeyError on
    unknown spec; raises clear KeyError listing available specs.
    """
    provider = CredentialProvider()
    with pytest.raises(KeyError, match="not registered"):
        await provider.get("nonexistent")


@pytest.mark.unit
async def test_resolve_unsupported_ref_format_raises_value_error() -> None:
    """Cycle 59 fix: unknown secret_ref format now raises ValueError
    (was silently returning {} → connectors connected with no auth).
    """
    provider = CredentialProvider()
    provider.register_spec(
        CredentialSpec(name="bad", secret_ref="file:/etc/passwd"),
    )
    with pytest.raises(ValueError, match="unsupported secret_ref format"):
        await provider.get("bad")


@pytest.mark.unit
async def test_resolve_missing_env_var_raises_keyerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle 59 fix: missing env var raises KeyError (was returning '')."""
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
    provider = CredentialProvider()
    provider.register_spec(
        CredentialSpec(name="missing", secret_ref="env:DEFINITELY_NOT_SET"),
    )
    with pytest.raises(KeyError, match="DEFINITELY_NOT_SET"):
        await provider.get("missing")


# ── Cycle 60 L8: audit-emit regression tests ──────────────────────────────


@pytest.mark.unit
async def test_get_emits_audit_on_cache_miss_and_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle 60 L8: emit_secret_access fires on cache miss + cache hit."""
    from src.backend.core.audit.facade import audit_service

    captured: list[dict[str, object]] = []

    async def fake_emit(self: object, **kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(audit_service.AuditService, "emit", fake_emit)

    monkeypatch.setenv("AUDIT_TEST_KEY", "secret-value")
    provider = CredentialProvider()
    provider.register_spec(
        CredentialSpec(
            name="audited",
            secret_ref="env:AUDIT_TEST_KEY",
            ttl_seconds=60,
        ),
    )

    await provider.get("audited", actor="test-user")
    await provider.get("audited", actor="test-user")

    secret_events = [e for e in captured if e.get("event") == "secret.access"]
    miss_events = [
        e for e in secret_events if e.get("details", {}).get("cache_status") == "miss"
    ]
    hit_events = [
        e for e in secret_events if e.get("details", {}).get("cache_status") == "hit"
    ]
    assert len(miss_events) == 1
    assert miss_events[0]["outcome"] == "success"
    assert miss_events[0]["actor"] == "test-user"
    assert "resolution_id" in miss_events[0]["details"]
    assert len(hit_events) == 1
    assert hit_events[0]["outcome"] == "success"
    assert hit_events[0]["actor"] == "test-user"


@pytest.mark.unit
async def test_get_emits_failure_audit_on_unknown_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle 60 L8: emit_secret_access fires with outcome=failure on unknown spec."""
    from src.backend.core.audit.facade import audit_service

    captured: list[dict[str, object]] = []

    async def fake_emit(self: object, **kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(audit_service.AuditService, "emit", fake_emit)

    provider = CredentialProvider()
    with pytest.raises(KeyError, match="not registered"):
        await provider.get("nonexistent", actor="test-user")

    secret_events = [e for e in captured if e.get("event") == "secret.access"]
    assert len(secret_events) == 1
    assert secret_events[0]["outcome"] == "failure"
    assert secret_events[0]["details"]["error_class"] == "KeyError"
    assert secret_events[0]["actor"] == "test-user"


@pytest.mark.unit
async def test_get_emits_failure_audit_on_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle 60 L8: emit_secret_access fires with outcome=failure on missing env var."""
    from src.backend.core.audit.facade import audit_service

    captured: list[dict[str, object]] = []

    async def fake_emit(self: object, **kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(audit_service.AuditService, "emit", fake_emit)

    monkeypatch.delenv("DEFINITELY_NOT_SET_2", raising=False)
    provider = CredentialProvider()
    provider.register_spec(
        CredentialSpec(name="m2", secret_ref="env:DEFINITELY_NOT_SET_2"),
    )
    with pytest.raises(KeyError, match="DEFINITELY_NOT_SET_2"):
        await provider.get("m2", actor="test-user")

    secret_events = [e for e in captured if e.get("event") == "secret.access"]
    assert len(secret_events) == 1
    assert secret_events[0]["outcome"] == "failure"
    assert secret_events[0]["details"]["error_class"] == "KeyError"


# ── S57 W2 coverage ratchet: edge cases on empty vault/env paths + singleton ──


@pytest.mark.unit
async def test_resolve_vault_empty_path_raises_value_error() -> None:
    """vault: prefix with no path → ValueError (credential_provider.py:157-160)."""
    provider = CredentialProvider()
    provider.register_spec(CredentialSpec(name="empty-vault", secret_ref="vault:"))
    with pytest.raises(ValueError, match="empty vault path"):
        await provider.get("empty-vault")


@pytest.mark.unit
async def test_resolve_vault_returns_none_raises_keyerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vault returns None → KeyError (credential_provider.py:163-166)."""
    backend = AsyncMock(spec=SecretsBackend)
    backend.get_secret.return_value = None
    monkeypatch.setattr(
        "src.backend.core.svcs_registry.get_service",
        lambda _contract: backend,
    )
    provider = CredentialProvider()
    provider.register_spec(
        CredentialSpec(name="none-vault", secret_ref="vault:secret/missing"),
    )
    with pytest.raises(KeyError, match="Vault returned None"):
        await provider.get("none-vault")


@pytest.mark.unit
async def test_resolve_env_empty_var_name_raises_value_error() -> None:
    """env: prefix with no var name → ValueError (credential_provider.py:173-176)."""
    provider = CredentialProvider()
    provider.register_spec(CredentialSpec(name="empty-env", secret_ref="env:"))
    with pytest.raises(ValueError, match="empty env var name"):
        await provider.get("empty-env")


@pytest.mark.unit
def test_get_credential_provider_lazy_init_creates_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_credential_provider: creates new instance when _instance is None (L201-203).

    Tests the lazy-init fallback branch: when module-level ``_instance`` is
    None on first call, a fresh CredentialProvider is created and cached.
    Subsequent calls return the cached instance (cached branch).
    """
    from src.backend.core.security import credential_provider as cp_mod

    # Save + restore to avoid leaking singleton state across tests
    monkeypatch.setattr(cp_mod, "_instance", None)

    instance1 = cp_mod.get_credential_provider()
    assert isinstance(instance1, cp_mod.CredentialProvider)

    # Second call returns the SAME instance (cached, no re-init)
    instance2 = cp_mod.get_credential_provider()
    assert instance1 is instance2
