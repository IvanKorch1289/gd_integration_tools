from typing import Dict

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseYAMLSettings


__all__ = (
    "SKBAPISettings",
    "skb_api_settings",
    "DadataAPISettings",
    "dadata_api_settings",
)


class SKBAPISettings(BaseYAMLSettings):
    """Configuration settings for integration with SKB-Tekhno API.

    Configuration sections:
    - Authentication: API credentials and base URL
    - Request configuration: Endpoints and priority settings
    - Timeouts: Connection and response timeout settings
    """

    yaml_group = "skb"
    model_config = SettingsConfigDict(
        env_prefix="SKB_",
        extra="forbid",
        frozen=True,  # Optional: Prevent accidental modifications
    )

    # Authentication
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

    # Request Configuration
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

    # Timeouts
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
skb_api_settings = SKBAPISettings()


class DadataAPISettings(BaseYAMLSettings):
    """Configuration settings for integration with Dadata API.

    Configuration sections:
    - Authentication: API credentials and base URL
    - Geolocation: Geographical search parameters
    - Rate limits: API usage restrictions
    """

    yaml_group = "dadata"
    model_config = SettingsConfigDict(
        env_prefix="DADATA_", extra="forbid", frozen=True
    )

    # Authentication
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

    # Geolocation
    endpoints: Dict[str, str] = Field(
        ...,
        description="API endpoint paths relative to base URL",
        examples=[{"geolocate": "/geolocate", "suggest": "/suggest"}],
    )
    geolocate_radius: int = Field(
        ..., description="Default search radius in meters", examples=[1000]
    )

    # Rate Limits
    max_requests_per_second: int = Field(
        ..., description="Maximum allowed requests per second", examples=[10]
    )


# Instantiate settings for immediate use
dadata_api_settings = DadataAPISettings()
