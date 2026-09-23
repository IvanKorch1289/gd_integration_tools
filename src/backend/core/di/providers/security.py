"""Security providers — HMAC signature builder, antivirus, Vault.

W9 P2-13 Phase 2 (cycle 153, MINIMAX plan): извлечено из
``core/di/providers/cache.py`` (868 LOC god-module, misattributed during
M2-#11 batch 13, 17). Cache.py содержал signature_builder (HMAC),
antivirus_backend_factory (AV scanning) и Vault secrets — все три логически
security/secrets concerns, не cache.

Back-compat: ``core/di/providers/cache.py`` продолжает re-export этих
функций через lazy ``__getattr__`` proxy (см. ADR-0321).

Singleton cache ``_overrides`` is per-domain (NOT shared) — каждый domain
имеет свой override-словарь для изоляции тестов.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


# ─────────────── HMAC signature builder ───────────────


def get_signature_builder_provider() -> Any:
    """Возвращает callable ``build_signature_headers`` (HMAC headers)."""
    if "signature_builder" in _overrides:
        return _overrides["signature_builder"]
    module = resolve_module("security.signatures")
    return module.build_signature_headers


def set_signature_builder_provider(builder: Any) -> None:
    """Установить override для ``signature_builder`` provider (test-инжекция)."""
    _overrides["signature_builder"] = builder


# ─── S78 M2-#11 batch 13: antivirus backend factory ───────────


def get_antivirus_backend_factory_provider() -> Any:
    r"""Возвращает :func:\`create_antivirus_backend\` factory.

    S78 M2-#11 batch 13: lazy resolve для dsl/processors/scan_file.py.
    """
    if "antivirus_backend_factory" in _overrides:
        return _overrides["antivirus_backend_factory"]
    module = resolve_module("antivirus.factory")
    return module.create_antivirus_backend


def set_antivirus_backend_factory_provider(factory: Any) -> None:
    """Test-override для antivirus backend factory (Sprint 78+)."""
    _overrides["antivirus_backend_factory"] = factory


# ─── S82 M2-#11 batch 17: Vault providers ─────────────────────


def get_vault_backend_class_provider() -> Any:
    r"""Возвращает :class:\`VaultBackend\` (secrets).

    S82 M2-#11 batch 17: lazy resolve для dsl/processors/vault_secret.py.
    """
    if "vault_backend_class" in _overrides:
        return _overrides["vault_backend_class"]
    module = resolve_module("secrets.vault_backend")
    return module.VaultBackend


def set_vault_backend_class_provider(aclass: Any) -> None:
    """Test-override для VaultBackend class (Sprint 82+)."""
    _overrides["vault_backend_class"] = aclass


def get_vault_config_class_provider() -> Any:
    r"""Возвращает :class:\`VaultConfig\` (secrets config).

    S82 M2-#11 batch 17: lazy resolve для dsl/processors/vault_secret.py.
    """
    if "vault_config_class" in _overrides:
        return _overrides["vault_config_class"]
    module = resolve_module("secrets.vault_client")
    return module.VaultConfig


def set_vault_config_class_provider(aclass: Any) -> None:
    """Test-override для VaultConfig class (Sprint 82+)."""
    _overrides["vault_config_class"] = aclass


__all__ = (
    "get_antivirus_backend_factory_provider",
    "get_signature_builder_provider",
    "get_vault_backend_class_provider",
    "get_vault_config_class_provider",
    "set_antivirus_backend_factory_provider",
    "set_signature_builder_provider",
    "set_vault_backend_class_provider",
    "set_vault_config_class_provider",
)
