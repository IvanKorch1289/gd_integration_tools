"""ConnectorManifest — typed connector schema (25.09 audit #10).

Per v6 §10 + 25.09 audit: «Typed ConnectorManifest: auth, capabilities,
pagination, rate limits, webhooks, data classification».

Этот модуль определяет ``ConnectorManifest`` — типизированную модель для
external connector'ов (HTTP/SOAP/gRPC/REST APIs). Расширяет базовый
``PluginManifest`` connector-специфичными полями:

- ``auth`` (api_key, oauth2, basic, mTLS);
- ``capabilities`` (список операций);
- ``pagination`` (cursor/offset/none);
- ``rate_limits`` (RPS, burst, backoff);
- ``webhooks`` (signature verification, retries);
- ``data_classification`` (PII levels для input/output).

Используется:
1. ``gd connector certify <plugin>`` — runtime certification (validate +
   smoke tests: timeout/429/5xx/schema-drift/replay);
2. Auto-codegen OpenAPI/AsyncAPI/MCP spec из manifest.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.backend.core.plugin_runtime.manifest_toml import PluginManifest

__all__ = (
    "AuthConfig",
    "ConnectorAuthType",
    "ConnectorManifest",
    "DataClassification",
    "PaginationConfig",
    "RateLimitConfig",
    "WebhookConfig",
)


class ConnectorAuthType(str, Enum):
    """Поддерживаемые типы auth для connector'ов."""

    NONE = "none"  # public API
    API_KEY = "api_key"  # X-API-Key header
    BASIC = "basic"  # HTTP Basic Auth
    OAUTH2 = "oauth2"  # OAuth2 client_credentials / authorization_code
    BEARER = "bearer"  # Bearer token
    MTLS = "mtls"  # Mutual TLS (mTLS) — для B2B интеграций


class DataClassification(str, Enum):
    """PII/data classification уровни (per ADR-044 privacy tiers)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"
    SENSITIVE_PII = "sensitive_pii"


class AuthConfig(BaseModel):
    """Конфигурация authentication для connector'а.

    Attributes:
        type: тип auth (api_key, oauth2, basic, mTLS).
        secret_ref: dotted-path к secret в Vault/secret manager.
        scopes: для OAuth2 — required scopes (например ``["read:invoices"]``).
        cert_path: для mTLS — путь к client certificate (PEM).
        rotation_days: рекомендуемая ротация credentials (days).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: ConnectorAuthType = ConnectorAuthType.NONE
    secret_ref: str | None = None
    scopes: tuple[str, ...] = ()
    cert_path: str | None = None
    rotation_days: int = 90

    @field_validator("secret_ref")
    @classmethod
    def _secret_ref_format(cls, v: str | None) -> str | None:
        # Per security best practice: secrets должны быть dotted-path в vault://...
        if v is None:
            return None
        if not (v.startswith("vault://") or v.startswith("env://") or v.startswith("file://")):
            raise ValueError(
                f"secret_ref должен начинаться с vault://, env:// или file://. Got: {v!r}"
            )
        return v


class PaginationConfig(BaseModel):
    """Конфигурация pagination для list endpoints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: Literal["none", "offset", "cursor", "page"] = "none"
    default_page_size: int = Field(default=100, ge=1, le=10000)
    max_page_size: int = Field(default=1000, ge=1, le=100000)


class RateLimitConfig(BaseModel):
    """Rate limits для connector'а (per ADR-044 throttling policy)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requests_per_second: float = Field(default=10.0, gt=0, le=10000)
    burst: int = Field(default=20, ge=1, le=10000)
    backoff_strategy: Literal["fixed", "exponential", "jittered"] = "exponential"
    max_retries: int = Field(default=3, ge=0, le=10)
    max_backoff_seconds: int = Field(default=60, ge=1, le=3600)


class WebhookConfig(BaseModel):
    """Конфигурация incoming webhooks от external API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    signature_header: str | None = None  # e.g., "X-Hub-Signature-256"
    signature_algorithm: Literal["hmac-sha256", "jws", "none"] = "hmac-sha256"
    max_retries: int = Field(default=5, ge=0, le=10)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class ConnectorManifest(BaseModel):
    """Typed ConnectorManifest (расширяет PluginManifest).

    Per 25.09 audit: «Typed ConnectorManifest: auth, capabilities,
    pagination, rate limits, webhooks, data classification».

    Attributes:
        base: базовый :class:`PluginManifest` с name/version/etc.
        endpoint: base URL connector'а (например ``https://api.example.com/v1``).
        auth: конфигурация authentication.
        pagination: pagination config для list endpoints.
        rate_limits: rate limiting config.
        webhooks: incoming webhooks config.
        data_classification: data sensitivity level (PII / confidential / etc).
        operations: список операций connector'а (например
            ``["invoices.list", "invoices.create"]``).
        openapi_spec: optional путь к OpenAPI 3.0+ spec для codegen.

    Examples:
        >>> from src.backend.core.connector.manifest import (
        ...     ConnectorManifest,
        ...     AuthConfig,
        ...     ConnectorAuthType,
        ... )
        >>> m = ConnectorManifest.from_plugin_manifest(
        ...     base=PluginManifest(name="dadata", version="1.0.0", ...),
        ...     endpoint="https://suggestions.dadata.ru/api/v2",
        ...     auth=AuthConfig(type=ConnectorAuthType.API_KEY, secret_ref="vault://dadata/api_key"),
        ... )
        >>> m.endpoint
        'https://suggestions.dadata.ru/api/v2'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    base: PluginManifest
    endpoint: str = Field(min_length=1, pattern=r"^https?://[\w./-]+$")
    auth: AuthConfig = Field(default_factory=AuthConfig)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)
    webhooks: WebhookConfig = Field(default_factory=WebhookConfig)
    data_classification: DataClassification = DataClassification.INTERNAL
    operations: tuple[str, ...] = ()
    openapi_spec: str | None = None

    @field_validator("operations")
    @classmethod
    def _operations_format(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        # Operations: dotted names (``<resource>.<verb>``).
        for op in v:
            if not op or "." not in op:
                raise ValueError(
                    f"operation должен быть dotted-name '<resource>.<verb>'. Got: {op!r}"
                )
            parts = op.split(".")
            if len(parts) < 2 or any(not p for p in parts):
                raise ValueError(
                    f"operation должен быть dotted-name '<resource>.<verb>'. Got: {op!r}"
                )
        return v

    @classmethod
    def from_plugin_manifest(
        cls,
        base: PluginManifest,
        endpoint: str,
        auth: AuthConfig | None = None,
        **kwargs: Any,
    ) -> "ConnectorManifest":
        """Convenience constructor: ConnectorManifest from existing PluginManifest.

        Args:
            base: базовый :class:`PluginManifest` (name/version/entry_class).
            endpoint: base URL connector'а.
            auth: :class:`AuthConfig` или ``None`` для default (no auth).
            **kwargs: прочие optional fields.

        Returns:
            Полный :class:`ConnectorManifest`.
        """
        return cls(
            base=base,
            endpoint=endpoint,
            auth=auth or AuthConfig(),
            **kwargs,
        )
