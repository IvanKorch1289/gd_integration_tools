"""SMS-настройки (IL2.2).

Конфигурация endpoint'ов и параметров для российских SMS-провайдеров.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("SMSSettings", "sms_settings")


class SMSSettings(BaseSettingsWithLoader):
    """Конфигурация SMS-провайдеров."""

    yaml_group: ClassVar[str] = "sms"
    model_config = SettingsConfigDict(env_prefix="SMS_", extra="forbid")

    mts_url: str = Field(
        default="https://api.mts.ru/sms/v1/send",
        description="Endpoint МТС для отправки SMS.",
    )
    megafon_url: str = Field(
        default="https://a2p-api.megafon.ru/sms/send",
        description="Endpoint МегаФон для отправки SMS.",
    )
    smsru_url: str = Field(
        default="https://sms.ru/sms/send",
        description="Endpoint SMS.ru для отправки SMS.",
    )


sms_settings = SMSSettings()
