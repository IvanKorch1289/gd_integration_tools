from typing import ClassVar, List, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseSettingsWithLoader


__all__ = (
    "SecureSettings",
    "secure_settings",
)


class SecureSettings(BaseSettingsWithLoader):
    """Authentication and authorization system configuration.

    Groups of parameters:
    - Token core settings
    - Algorithms and keys
    - Additional settings
    """

    yaml_group: ClassVar[str] = "security"
    model_config = SettingsConfigDict(
        env_prefix="SEC_",
        extra="forbid",
    )

    token_name: str = Field(
        ...,
        description="Name of the HTTP cookie/header containing the token",
        examples=["access_token", "auth_token"],
    )
    token_lifetime: int = Field(
        ...,
        ge=60,
        description="Token lifetime in seconds (minimum 60)",
        examples=[3600, 86400],
    )
    refresh_token_lifetime: int = Field(
        ...,
        ge=3600,
        description="Refresh token lifetime in seconds (default 30 days)",
        examples=[2592000, 86400],
    )
    secret_key: str = Field(
        ...,
        min_length=32,
        description="Secret key for token signing (minimum 32 characters)",
        examples=["supersecretkeywithatleast32characters123"],
    )
    algorithm: Literal["HS256", "HS384", "HS512", "RS256"] = Field(
        ...,
        description="Token signing algorithm",
        examples=["HS256", "RS256"],
    )
    cookie_secure: bool = Field(
        ...,
        description="Transmit token only over HTTPS",
        examples=[True, False],
    )
    cookie_samesite: Literal["lax", "strict", "none"] = Field(
        ...,
        description="SameSite policy for cookies",
        examples=["lax", "strict", "none"],
    )
    api_key: str = Field(
        ...,
        description="Main application API key",
        examples=["your_api_key_123"],
    )
    allowed_hosts: List[str] = Field(
        ...,
        description="Allowed hosts for incoming requests",
        examples=[["example.com", "api.example.com"]],
    )
    routes_without_api_key: List[str] = Field(
        ...,
        description="Endpoints accessible without the application API key",
        examples=[["/health", "/status"]],
    )
    request_timeout: float = Field(
        ...,
        description="Maximum request timeout in seconds",
        examples=[5.0, 10.0],
    )
    rate_limit: int = Field(
        ...,
        description="Number of requests per minute allowed for the application",
        examples=[100, 500],
    )
    rate_time_measure_seconds: int = Field(
        ...,
        description="Time window for rate limiting in seconds",
        examples=[60, 300],
    )
    failure_threshold: int = Field(
        ...,
        description="Number of failed request attempts before locking the account",
        examples=[5, 10],
    )
    recovery_timeout: int = Field(
        ...,
        description="Time after which the account is unlocked after failed attempts",
        examples=[600, 3600],
    )


# Instantiate settings for immediate use
secure_settings = SecureSettings()
