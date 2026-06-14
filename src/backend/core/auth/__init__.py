"""Базовые типы авторизации (Wave 8.1).

Содержит ``AuthMethod`` enum и ``AuthContext`` value-object — минимальные
типы, нужные DSL-процессорам и любым другим слоям без знания о FastAPI
или верификаторах. Реальные verifier-функции и ``require_auth``-фабрика
живут в ``entrypoints/api/dependencies/auth_selector.py`` и собирают
эти типы при работе.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from src.backend.core.auth.api_key_backend import APIKeyAuth
from src.backend.core.auth.mtls_backend import (
    MtlsBackend,
    MtlsConfig,
    MtlsVerificationError,
    ParsedClientCert,
)
from src.backend.core.auth.saml_backend import (
    SamlAuthResult,
    SamlBackend,
    SamlConfig,
    SamlError,
)
from src.backend.core.auth.sso_registry import (
    HvacVaultClient,
    SsoRegistry,
    SsoRegistryError,
    SsoRegistrySchemaError,
    SsoRegistryVaultError,
    VaultClientProtocol,
)
from src.backend.core.auth.sso_types import GroupsToCapabilities, IdpConfig, SSOUserInfo

__all__ = (
    "APIKeyAuth",
    "AuthContext",
    "AuthMethod",
    "GroupsToCapabilities",
    "HvacVaultClient",
    "IdpConfig",
    "MtlsBackend",
    "MtlsConfig",
    "MtlsVerificationError",
    "ParsedClientCert",
    "SamlAuthResult",
    "SamlBackend",
    "SamlConfig",
    "SamlError",
    "SsoRegistry",
    "SsoRegistryError",
    "SsoRegistrySchemaError",
    "SsoRegistryVaultError",
    "SSOUserInfo",
    "VaultClientProtocol",
)


class AuthMethod(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    JWT = "jwt"
    BASIC = "basic"
    MTLS = "mtls"
    SAML = "saml"
    """V15 S6: SP-initiated SSO + SLO через python3-saml."""
    EXPRESS = "express"
    EXPRESS_JWT = "express_jwt"


class AuthContext:
    """Контекст авторизованного запроса."""

    __slots__ = ("metadata", "method", "principal")

    def __init__(
        self, method: AuthMethod, principal: str, metadata: dict[str, Any] | None = None
    ) -> None:
        self.method = method
        self.principal = principal
        self.metadata = metadata or {}
