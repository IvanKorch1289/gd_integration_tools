from typing import ClassVar, Dict, List

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseYAMLSettings


__all__ = (
    "SKBAPISettings",
    "skb_api_settings",
    "DadataAPISettings",
    "dadata_api_settings",
)


class HttpBaseSettings(BaseYAMLSettings):
    yaml_group: ClassVar[str] = "http"
    model_config = SettingsConfigDict(
        env_prefix="HTTP_",
        extra="forbid",
    )

    max_retries: int = Field(
        ...,
        description="Maximum retries for HTTP requests",
        examples=10,
    )
    retry_backoff_factor: float = Field(
        ...,
        description="Retry factor",
        examples=2.5,
    )
    retry_status_codes: List[int] = Field(
        ...,
        description="Status codes for HTTP requests with retry_backoff",
        examples=[404, 500],
    )
    total_timeout: int = Field(
        ...,
        description="Total timeout for HTTP requests",
        examples=60,
    )
    connect_timeout: int = Field(
        ...,
        description="Timeout for TCP connection",
        examples=60,
    )
    sock_read_timeout: int = Field(
        ...,
        description="Timeout for reading HTTP requests",
        examples=60,
    )
    keepalive_timeout: int = Field(
        ...,
        description="Timeout for keepalive connections",
        examples=600,
    )
    limit: int = Field(
        ...,
        description="The total number of simultaneous connections",
        examples=30,
    )
    limit_per_host: int = Field(
        ...,
        description="Number of simultaneous connections to one host",
        examples=30,
    )
    ttl_dns_cache: int = Field(
        ...,
        description="Max seconds having cached a DNS entry",
        examples=300,
    )
    ttl_dns_cache: int = Field(
        ...,
        description="Max seconds having cached a DNS entry",
        examples=300,
    )
    force_close: bool = Field(
        ...,
        description="Force close and do reconnect after each request",
        examples=True,
    )


class SKBAPISettings(BaseYAMLSettings):
    """Configuration settings for integration with SKB-Tekhno API."""

    yaml_group: ClassVar[str] = "skb"
    model_config = SettingsConfigDict(
        env_prefix="SKB_",
        extra="forbid",
    )

    api_key: str = Field(
        ...,
        description="Secret key for API access",
        examples=["your-api-key-here"],
    )
    base_url: str = Field(
        ...,
        description="Base API URL without endpoints",
        examples=["https://api.skb-tekhno.ru/v1"],
    )
    endpoints: Dict[str, str] = Field(
        ...,
        description="API endpoint paths relative to base URL",
        examples=[{"users": "/users", "orders": "/orders"}],
    )
    default_priority: int = Field(
        ...,
        ge=1,
        le=100,
        description="Default request priority (1-100)",
        examples=[50],
    )
    connect_timeout: float = Field(
        ...,
        description="Maximum connection establishment time in seconds",
        examples=[5.0],
    )
    read_timeout: float = Field(
        ...,
        description="Maximum response wait time in seconds",
        examples=[30.0],
    )


class DadataAPISettings(BaseYAMLSettings):
    """Configuration settings for integration with Dadata API."""

    yaml_group: ClassVar[str] = "dadata"
    model_config = SettingsConfigDict(
        env_prefix="DADATA_",
        extra="forbid",
    )

    api_key: str = Field(
        ...,
        description="Secret key for Dadata API access",
        examples=["dadata-secret-key"],
    )
    base_url: str = Field(
        ...,
        description="Base API URL without endpoint paths",
        examples=["https://suggestions.dadata.ru/suggestions/api/4_1/rs"],
    )
    endpoints: Dict[str, str] = Field(
        ...,
        description="API endpoint paths relative to base URL",
        examples=[{"geolocate": "/geolocate", "suggest": "/suggest"}],
    )
    geolocate_radius_default: int = Field(
        ..., description="Default search radius in meters", examples=[1000]
    )
    connect_timeout: float = Field(
        ...,
        description="Maximum connection establishment time in seconds",
        examples=[5.0],
    )
    read_timeout: float = Field(
        ...,
        description="Maximum response wait time in seconds",
        examples=[30.0],
    )


# Instantiate settings for immediate use
http_base_settings = HttpBaseSettings()
skb_api_settings = SKBAPISettings()
dadata_api_settings = DadataAPISettings()
