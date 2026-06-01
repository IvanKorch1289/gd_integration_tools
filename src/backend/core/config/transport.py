"""Конфигурация транспортных клиентов (SFTP/FTP).

Sprint 17 W1 (b2 partial closure): добавляет strict-mode для SFTP
``known_hosts``-валидации. По умолчанию путь не задан и в dev-профиле
``known_hosts``-проверка пропускается; в production без явного пути клиент
обязан подняться с ``ValueError`` (V1 security constraint).

Подключается в :class:`src.backend.core.config.settings.Settings` через
поле ``transport: TransportSettings``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ("TransportSettings", "transport_settings")


class TransportSettings(BaseSettings):
    """Настройки транспортных клиентов (SFTP/FTP).

    Attributes:
        sftp_known_hosts_path: Путь к файлу ``known_hosts`` для строгой
            проверки SFTP-серверного ключа. Если ``None`` и активный
            профиль ``dev_light``, проверка пропускается (``known_hosts=()``).
            В production ``None`` приводит к ``ValueError`` (V1 запрещает
            ``CERT_NONE`` / отключение проверок без явной декларации).
    """

    model_config = SettingsConfigDict(env_prefix="TRANSPORT_", extra="ignore")

    sftp_known_hosts_path: str | None = Field(
        default=None,
        description=(
            "Путь к ``known_hosts``-файлу для строгой SFTP-валидации. "
            "В production обязателен; в dev_light допускается None (skip)."
        ),
        examples=["/etc/gd/known_hosts", "~/.ssh/known_hosts"],
    )


transport_settings = TransportSettings()
