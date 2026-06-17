"""WebSocket service settings (S163 W13).

Ранее WS не имел settings вообще — `ws_handler.py` использовал хардкод
без timeout/heartbeat/concurrent-limit. Per R-V15-14 connection pool
обязателен для всех backend-clients, включая WS.

DSL override (per-route): ``route.toml::[transport.ws] max_message_size``,
``heartbeat_interval_s``, ``message_timeout_s`` — реализуется в S163 W14
(wire route.toml → WS handler).

Pattern: ``MailSettings`` / ``CacheSettings`` — BaseSettingsWithLoader +
yaml_group + env_prefix.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("WSSettings", "ws_settings")


class WSSettings(BaseSettingsWithLoader):
    """Стандартные настройки WebSocket-сервиса.

    Используются в ``entrypoints/websocket/ws_handler.py`` для:
        * ограничения concurrent-подключений (pool)
        * per-message timeout (защита от hung clients)
        * heartbeat interval (auto-ping для keepalive)
        * max message size (защита от OOM)

    Per-route override через ``route.toml::[transport.ws]`` (S163 W14).
    """

    yaml_group: ClassVar[str] = "websocket"
    model_config = SettingsConfigDict(env_prefix="WS_", extra="forbid")

    # Pool: max concurrent WS connections.
    max_connections: int = Field(
        default=1000,
        ge=1,
        description="Максимум одновременных WS-подключений (pool size).",
    )

    # Per-message timeout (защита от slow clients).
    message_timeout_s: float = Field(
        default=30.0,
        gt=0,
        description="Таймаут на обработку одного сообщения (секунды).",
    )

    # Heartbeat (auto-ping для keepalive).
    heartbeat_interval_s: float = Field(
        default=30.0,
        gt=0,
        description="Интервал ping/pong для keepalive (секунды). 0 = disabled.",
    )

    # Max message size (защита от OOM при больших payload).
    max_message_size: int = Field(
        default=65536,  # 64KB
        gt=0,
        description="Максимальный размер одного WS-сообщения (bytes).",
    )

    # ── Rate limiting (S164 W36) ────────────────────────────────────

    rate_limit_per_minute: int = Field(
        default=600,
        gt=0,
        description="Лимит WS-сообщений per minute per tenant/user/IP identifier.",
    )
    rate_limit_burst: int = Field(
        default=10,
        gt=0,
        description="Token-bucket burst size для rate limiting.",
    )


ws_settings = WSSettings()
"""Глобальный экземпляр WSSettings (lazy-resolved через BaseSettingsWithLoader)."""
