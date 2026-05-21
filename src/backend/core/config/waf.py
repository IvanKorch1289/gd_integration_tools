"""Конфигурация WAF (Wave 1.4 / S1).

Описывает глобальную :class:`WafPolicy`, применяемую :class:`OutboundHttpClient`
ко всем ``net.outbound:<host>:external`` запросам. Поведение настраивается
через env (``WAF_*``) или yaml-config (group ``waf``).

* ``allow_hosts`` — whitelist хостов; пустой допускает любые (если ``strict=False``);
* ``deny_hosts`` — приоритетный blacklist;
* ``strict`` — пустой allowlist трактуется как deny-all (R3 prod-gate);
* ``max_payload_bytes`` — лимит body, по умолчанию 10 MiB.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("WafSettings", "waf_settings")


class WafSettings(BaseSettingsWithLoader):
    """Декларативные настройки WAF-policy."""

    yaml_group: ClassVar[str] = "waf"
    model_config = SettingsConfigDict(env_prefix="WAF_", extra="ignore")

    allow_hosts: tuple[str, ...] = Field(
        default=(), description="Whitelist хостов (пусто — allow-all при strict=False)."
    )

    deny_hosts: tuple[str, ...] = Field(
        default=(), description="Blacklist хостов; имеет приоритет над allow."
    )

    strict: bool = Field(
        default=False,
        description="При True пустой allow_hosts трактуется как deny-all.",
    )

    max_payload_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=0,
        description="Максимальный размер body исходящего запроса (байты).",
    )

    outbound_via_facade: bool = Field(
        default=True,
        description=(
            "Phase-1 (False): legacy HTTP-клиент остаётся; "
            "Phase-2 (True, default): BaseExternalAPIClient + субклассы "
            "идут через OutboundHttpClient (auto-routing). "
            "См. ADR-0053 для миграционной стратегии и follow-up callsites."
        ),
    )


waf_settings = WafSettings()
"""Глобальный экземпляр WafSettings."""
