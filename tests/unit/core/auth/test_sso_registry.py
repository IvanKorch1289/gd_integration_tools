"""Unit-тесты :class:`SsoRegistry` (Sprint 125 W2).

Покрывает:

* Read-through cache: hit/miss/expiration
* Per-tenant isolation
* TTL invalidation (manual + bulk)
* Vault errors → graceful degradation (stale fallback или ``None``)
* Pydantic validation: missing fields, invalid schema
* HvacVaultClient: ENV fallback, lazy import
* GroupsToCapabilities.resolve: union + dedup

Pattern: fake :class:`VaultClientProtocol` (deterministic, no network).
Per-tenant asyncio.Lock concurrency protection.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.core.auth.sso_registry import (
    DEFAULT_TTL_SECONDS,
    DEFAULT_VAULT_PATH_PREFIX,
    HvacVaultClient,
    SsoRegistry,
    SsoRegistryError,
    SsoRegistrySchemaError,
    SsoRegistryVaultError,
)
from src.backend.core.auth.sso_types import (
    GROUPS_TO_CAPABILITIES_KEY,
    GroupsToCapabilities,
    IdpConfig,
)

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeVaultClient:
    """In-memory fake для :class:`VaultClientProtocol` (deterministic)."""

    def __init__(self, payloads: dict[str, dict[str, Any]] | None = None) -> None:
        self._payloads = payloads or {}
        self.call_count: dict[str, int] = {}
        self.fail_paths: set[str] = set()

    def set_payload(self, path: str, payload: dict[str, Any]) -> None:
        self._payloads[path] = payload

    def fail_for(self, path: str) -> None:
        self.fail_paths.add(path)

    def read_secret(self, path: str) -> dict[str, Any]:
        self.call_count[path] = self.call_count.get(path, 0) + 1
        if path in self.fail_paths:
            raise SsoRegistryVaultError(f"Simulated Vault failure for {path!r}")
        if path not in self._payloads:
            raise SsoRegistryVaultError(f"Path not found: {path!r}")
        return dict(self._payloads[path])


def _valid_payload(tenant: str = "acme", **overrides: Any) -> dict[str, Any]:
    """Стандартный valid payload для tenant'а."""
    base: dict[str, Any] = {
        "entity_id": f"https://idp.{tenant}.example.com/saml",
        "sso_url": f"https://idp.{tenant}.example.com/sso",
        "x509_cert": "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
        "slo_url": f"https://idp.{tenant}.example.com/slo",
        "allow_create_user": True,
        GROUPS_TO_CAPABILITIES_KEY: {
            f"{tenant}-admins": ["admin.feature_flag:write"],
            f"{tenant}-users": ["user.profile:read"],
        },
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Path / lock helpers
# --------------------------------------------------------------------------- #


def test_path_for_uses_default_prefix() -> None:
    """Default prefix → ``secret/data/sso/<tenant>/idp`` (per ADR-0054 §2)."""
    fake = _FakeVaultClient()
    registry = SsoRegistry(vault_client=fake)
    assert registry._path_for("acme") == "secret/data/sso/acme/idp"


def test_path_for_respects_custom_prefix() -> None:
    """Custom prefix → ``<prefix>/<tenant>/idp``."""
    fake = _FakeVaultClient()
    registry = SsoRegistry(
        vault_path_prefix="custom/prefix",
        vault_client=fake,
    )
    assert registry._path_for("bank1") == "custom/prefix/bank1/idp"


# --------------------------------------------------------------------------- #
# Read-through cache: basic
# --------------------------------------------------------------------------- #


async def test_get_returns_parsed_idp_config() -> None:
    """``get(tenant)`` возвращает :class:`IdpConfig` из Vault payload."""
    fake = _FakeVaultClient({"secret/data/sso/acme/idp": _valid_payload("acme")})
    registry = SsoRegistry(vault_client=fake)
    config = await registry.get("acme")
    assert isinstance(config, IdpConfig)
    assert config.entity_id == "https://idp.acme.example.com/saml"
    assert config.sso_url == "https://idp.acme.example.com/sso"
    assert config.slo_url == "https://idp.acme.example.com/slo"
    assert config.allow_create_user is True
    assert config.groups_to_capabilities.mappings == {
        "acme-admins": ["admin.feature_flag:write"],
        "acme-users": ["user.profile:read"],
    }


async def test_get_caches_result() -> None:
    """Second ``get`` в TTL → не звонит в Vault (cache hit)."""
    fake = _FakeVaultClient({"secret/data/sso/acme/idp": _valid_payload("acme")})
    registry = SsoRegistry(vault_client=fake)
    await registry.get("acme")
    await registry.get("acme")
    await registry.get("acme")
    # Один Vault call total (cache hit на 2+3).
    assert fake.call_count["secret/data/sso/acme/idp"] == 1


async def test_get_returns_none_on_vault_failure_no_cache() -> None:
    """Vault error + нет cached value → ``None`` (graceful degradation)."""
    fake = _FakeVaultClient()
    fake.fail_for("secret/data/sso/acme/idp")
    registry = SsoRegistry(vault_client=fake)
    config = await registry.get("acme")
    assert config is None


async def test_get_returns_stale_on_vault_failure_with_cache() -> None:
    """Vault error + есть cached value → stale fallback (как JwksCache)."""
    fake = _FakeVaultClient({"secret/data/sso/acme/idp": _valid_payload("acme")})
    registry = SsoRegistry(vault_client=fake)
    # Первый call — success, кладёт в кеш.
    config_first = await registry.get("acme")
    assert config_first is not None
    # Теперь Vault fail'ит.
    fake.fail_for("secret/data/sso/acme/idp")
    # Второй call — возвращает stale (не None).
    config_second = await registry.get("acme")
    assert config_second is not None
    assert config_second.entity_id == config_first.entity_id


# --------------------------------------------------------------------------- #
# Per-tenant isolation
# --------------------------------------------------------------------------- #


async def test_per_tenant_isolation() -> None:
    """Разные tenants → разные Vault paths, разные cache entries."""
    fake = _FakeVaultClient(
        {
            "secret/data/sso/acme/idp": _valid_payload("acme"),
            "secret/data/sso/bank1/idp": _valid_payload("bank1"),
        }
    )
    registry = SsoRegistry(vault_client=fake)
    acme_config = await registry.get("acme")
    bank1_config = await registry.get("bank1")
    assert acme_config is not None
    assert bank1_config is not None
    assert acme_config.entity_id == "https://idp.acme.example.com/saml"
    assert bank1_config.entity_id == "https://idp.bank1.example.com/saml"
    # Каждый tenant = 1 Vault call.
    assert fake.call_count["secret/data/sso/acme/idp"] == 1
    assert fake.call_count["secret/data/sso/bank1/idp"] == 1


# --------------------------------------------------------------------------- #
# TTL expiration
# --------------------------------------------------------------------------- #


async def test_ttl_expiration_triggers_refresh() -> None:
    """TTL expiration → следующий ``get`` звонит в Vault (cache miss)."""
    fake = _FakeVaultClient({"secret/data/sso/acme/idp": _valid_payload("acme")})
    # TTL = 1 секунда — сможем проверить expiration через sleep.
    registry = SsoRegistry(ttl=1, vault_client=fake)
    await registry.get("acme")
    assert fake.call_count["secret/data/sso/acme/idp"] == 1
    # Sleep > TTL.
    await asyncio.sleep(1.1)
    await registry.get("acme")
    assert fake.call_count["secret/data/sso/acme/idp"] == 2


async def test_ttl_zero_means_always_fresh_disabled() -> None:
    """``ttl=0`` (sentinel) → invalidates immediately → next call refreshes.

    Edge case: JwksCache использует ``time.monotonic() + self._ttl``. Если
    ``ttl=0``, ``_expires_at`` = now, и сразу же ``time.monotonic() < _expires_at``
    False. Это OK — каждый call = refresh.
    """
    fake = _FakeVaultClient({"secret/data/sso/acme/idp": _valid_payload("acme")})
    registry = SsoRegistry(ttl=0, vault_client=fake)
    await registry.get("acme")
    await registry.get("acme")
    assert fake.call_count["secret/data/sso/acme/idp"] == 2


# --------------------------------------------------------------------------- #
# Manual invalidation (Vault audit-log)
# --------------------------------------------------------------------------- #


async def test_invalidate_clears_single_tenant() -> None:
    """``invalidate(tenant)`` → next ``get`` triggers Vault refresh."""
    fake = _FakeVaultClient({"secret/data/sso/acme/idp": _valid_payload("acme")})
    registry = SsoRegistry(vault_client=fake)
    await registry.get("acme")
    assert fake.call_count["secret/data/sso/acme/idp"] == 1
    registry.invalidate("acme")
    await registry.get("acme")
    assert fake.call_count["secret/data/sso/acme/idp"] == 2


async def test_invalidate_does_not_affect_other_tenants() -> None:
    """``invalidate(tenant_a)`` → ``tenant_b`` cache остаётся свежим."""
    fake = _FakeVaultClient(
        {
            "secret/data/sso/acme/idp": _valid_payload("acme"),
            "secret/data/sso/bank1/idp": _valid_payload("bank1"),
        }
    )
    registry = SsoRegistry(vault_client=fake)
    await registry.get("acme")
    await registry.get("bank1")
    registry.invalidate("acme")
    # bank1 cache hit (no Vault call).
    await registry.get("bank1")
    assert fake.call_count["secret/data/sso/bank1/idp"] == 1


async def test_invalidate_all_clears_everything() -> None:
    """``invalidate_all()`` → next ``get`` triggers refresh для всех tenants."""
    fake = _FakeVaultClient(
        {
            "secret/data/sso/acme/idp": _valid_payload("acme"),
            "secret/data/sso/bank1/idp": _valid_payload("bank1"),
        }
    )
    registry = SsoRegistry(vault_client=fake)
    await registry.get("acme")
    await registry.get("bank1")
    registry.invalidate_all()
    await registry.get("acme")
    await registry.get("bank1")
    assert fake.call_count["secret/data/sso/acme/idp"] == 2
    assert fake.call_count["secret/data/sso/bank1/idp"] == 2


# --------------------------------------------------------------------------- #
# Pydantic validation errors
# --------------------------------------------------------------------------- #


async def test_get_raises_schema_error_on_missing_required_field() -> None:
    """Missing ``entity_id`` → SsoRegistrySchemaError (propagates, не маскируется)."""
    payload = _valid_payload("acme")
    del payload["entity_id"]
    fake = _FakeVaultClient({"secret/data/sso/acme/idp": payload})
    registry = SsoRegistry(vault_client=fake)
    with pytest.raises(SsoRegistrySchemaError, match="Invalid IdP config schema"):
        await registry.get("acme")


async def test_get_raises_schema_error_on_invalid_x509_cert_type() -> None:
    """``x509_cert`` is not a string → SsoRegistrySchemaError (propagates)."""
    payload = _valid_payload("acme", x509_cert=12345)  # type: ignore[arg-type]
    fake = _FakeVaultClient({"secret/data/sso/acme/idp": payload})
    registry = SsoRegistry(vault_client=fake)
    with pytest.raises(SsoRegistrySchemaError, match="Invalid IdP config schema"):
        await registry.get("acme")


# --------------------------------------------------------------------------- #
# HvacVaultClient
# --------------------------------------------------------------------------- #


def test_hvac_vault_client_requires_env_or_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """HvacVaultClient без VAULT_ADDR/VAULT_TOKEN → SsoRegistryVaultError."""
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    client = HvacVaultClient()
    with pytest.raises(SsoRegistryVaultError, match="VAULT_ADDR"):
        client.read_secret("secret/data/sso/acme/idp")


# --------------------------------------------------------------------------- #
# GroupsToCapabilities.resolve
# --------------------------------------------------------------------------- #


def test_groups_to_capabilities_resolve_union() -> None:
    """``resolve([groups])`` → union всех capability-scope'ов."""
    g2c = GroupsToCapabilities(
        mappings={
            "admins": ["admin.feature_flag:write", "admin.tenants:read"],
            "users": ["user.profile:read"],
        }
    )
    caps = g2c.resolve(["admins", "users"])
    assert caps == [
        "admin.feature_flag:write",
        "admin.tenants:read",
        "user.profile:read",
    ]


def test_groups_to_capabilities_resolve_dedup() -> None:
    """Дубликаты cap-scope'ов из разных groups → дедупликация first-seen."""
    g2c = GroupsToCapabilities(
        mappings={
            "group_a": ["x:read", "y:write"],
            "group_b": ["y:write", "z:delete"],
        }
    )
    caps = g2c.resolve(["group_a", "group_b"])
    assert caps == ["x:read", "y:write", "z:delete"]


def test_groups_to_capabilities_resolve_empty_input() -> None:
    """Empty groups list → empty caps list."""
    g2c = GroupsToCapabilities(
        mappings={"admins": ["admin.feature_flag:write"]}
    )
    assert g2c.resolve([]) == []


def test_groups_to_capabilities_resolve_unknown_group() -> None:
    """Unknown group (не в mapping) → ignore silently."""
    g2c = GroupsToCapabilities(mappings={"admins": ["admin.x:write"]})
    assert g2c.resolve(["unknown"]) == []


# --------------------------------------------------------------------------- #
# Defaults (sanity check)
# --------------------------------------------------------------------------- #


def test_default_vault_path_prefix() -> None:
    """Default Vault path prefix = ``secret/data/sso`` (per ADR-0054 §2)."""
    assert DEFAULT_VAULT_PATH_PREFIX == "secret/data/sso"


def test_default_ttl_seconds() -> None:
    """Default TTL = 300s (per ADR-0054 §2)."""
    assert DEFAULT_TTL_SECONDS == 300


# --------------------------------------------------------------------------- #
# Exception hierarchy (sanity check)
# --------------------------------------------------------------------------- #


def test_sso_registry_vault_error_is_subclass_of_registry_error() -> None:
    """``SsoRegistryVaultError`` is a :class:`SsoRegistryError` (catch-all)."""
    assert issubclass(SsoRegistryVaultError, SsoRegistryError)


def test_sso_registry_schema_error_is_subclass_of_registry_error() -> None:
    """``SsoRegistrySchemaError`` is a :class:`SsoRegistryError` (catch-all)."""
    assert issubclass(SsoRegistrySchemaError, SsoRegistryError)
