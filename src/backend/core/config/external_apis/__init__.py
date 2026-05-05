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
    "antivirus_api_settings",
    "DadataAPISettings",
    "dadata_api_settings",
    "SKBAPISettings",
    "skb_api_settings",
)
