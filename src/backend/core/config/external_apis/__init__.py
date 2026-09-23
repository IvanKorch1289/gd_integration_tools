"""Конфиги внешних API-интеграций."""

from src.backend.core.config.external_apis.antivirus import (
    AntivirusAPISettings,
    antivirus_api_settings,
)
from src.backend.core.config.external_apis.dadata import (
    DadataAPISettings,
    dadata_api_settings,
)
from src.backend.core.config.external_apis.skb import SKBAPISettings, skb_api_settings

__all__ = (
    "AntivirusAPISettings",
    "DadataAPISettings",
    "SKBAPISettings",
    "antivirus_api_settings",
    "dadata_api_settings",
    "skb_api_settings",
)
