"""Конфиги внешних API-интеграций."""

from src.core.config.external_apis.antivirus_api import (
    AntivirusAPISettings,
    antivirus_api_settings,
)
from src.core.config.external_apis.dadata_api import (
    DadataAPISettings,
    dadata_api_settings,
)
from src.core.config.external_apis.skb_api import SKBAPISettings, skb_api_settings

__all__ = (
    "AntivirusAPISettings",
    "antivirus_api_settings",
    "DadataAPISettings",
    "dadata_api_settings",
    "SKBAPISettings",
    "skb_api_settings",
)
