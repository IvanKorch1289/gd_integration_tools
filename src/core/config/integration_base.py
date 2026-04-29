"""Базовая иерархия настроек интеграций (W15.2).

Назначение
----------
Унифицирует общие поля интеграционных настроек (таймауты, retry, флаг
включения) и постепенно расширяет контракт для двух типичных под-форм:

* ``BaseWebhookChannelSettings`` — внешняя сторона нас вызывает (callback,
  HMAC подпись, входящий webhook).
* ``BaseBotChannelSettings`` — мы исходяще шлём сообщения через bot-API
  (Express BotX, Telegram Bot API и т.п.).

Конкретные классы (``ExpressSettings``, ``TelegramBotSettings``) задают
свой ``yaml_group`` и ``env_prefix`` через ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = (
    "BaseBotChannelSettings",
    "BaseIntegrationSettings",
    "BaseWebhookChannelSettings",
)


class BaseIntegrationSettings(BaseSettingsWithLoader):
    """Базовый контракт outbound-интеграции (HTTP-клиент или канал).

    Наследники обязаны переопределить ``yaml_group`` и ``env_prefix``
    (через ``model_config``). Класс не предназначен для прямой
    инстанциации — он не задаёт ``yaml_group``.

    Поля:
        enabled: Включена ли интеграция (флаг feature toggle).
        connect_timeout: Таймаут установки TCP-соединения (сек.).
        read_timeout: Таймаут ожидания ответа после соединения (сек.).
        total_timeout: Полный лимит времени запроса; ``None`` отключает.
        max_retries: Кол-во повторов при временных ошибках.
        retry_backoff_factor: Множитель экспоненциальной паузы между
            повторами.
    """

    yaml_group: ClassVar[str | None] = None
    model_config = SettingsConfigDict(env_prefix="", extra="forbid")

    enabled: bool = Field(
        default=False,
        title="Включена",
        description="Включена ли интеграция",
        examples=[False, True],
    )
    connect_timeout: float = Field(
        default=10.0,
        title="Таймаут подключения",
        ge=0.1,
        description="Максимальное время установки соединения (секунды)",
        examples=[5.0, 10.0],
    )
    read_timeout: float = Field(
        default=30.0,
        title="Таймаут чтения",
        ge=0.1,
        description="Максимальное время ожидания ответа (секунды)",
        examples=[30.0],
    )
    total_timeout: float | None = Field(
        default=None,
        title="Общий таймаут",
        description=("Полный лимит времени запроса (секунды). ``None`` отключает."),
        examples=[60.0, None],
    )
    max_retries: int = Field(
        default=2,
        title="Количество повторов",
        ge=0,
        le=10,
        description="Количество повторных попыток при временных ошибках",
        examples=[2, 3],
    )
    retry_backoff_factor: float = Field(
        default=1.0,
        title="Коэффициент backoff",
        ge=0.0,
        description="Множитель экспоненциальной задержки между retry",
        examples=[0.5, 1.0, 2.0],
    )

    @model_validator(mode="after")
    def _validate_timeouts(self) -> BaseIntegrationSettings:
        """Проверяет согласованность таймаутов.

        ``connect_timeout`` должен быть строго меньше ``total_timeout``,
        если последний задан. ``read_timeout`` сам по себе не сравнивается
        с ``total_timeout`` (стек может тратить время на TLS-handshake
        и DNS до начала чтения).
        """
        if (
            self.total_timeout is not None
            and self.connect_timeout >= self.total_timeout
        ):
            raise ValueError("connect_timeout должен быть меньше total_timeout")
        return self


class BaseWebhookChannelSettings(BaseIntegrationSettings):
    """Канал на основе входящих webhook'ов.

    Расширяет базу полями для приёма callback'ов от внешней системы:
    публичный URL обратного вызова и секрет для верификации подписи
    (HMAC, JWT, mTLS-fingerprint и т.п.).

    Поля:
        callback_url: URL нашего сервиса, на который шлёт внешняя
            сторона (полный публичный URL, включая префикс роутера).
        signature_secret: Секрет для проверки подписи входящих
            запросов. Пустая строка означает отсутствие проверки.
        signature_header: Имя HTTP-заголовка с подписью.
    """

    callback_url: str = Field(
        default="",
        title="URL callback",
        description=(
            "Публичный URL нашего сервиса для приёма входящих событий "
            "от внешней системы"
        ),
        examples=["https://api.example.com/webhooks/express"],
    )
    signature_secret: str = Field(
        default="",
        title="Секрет подписи",
        description=(
            "Секретный ключ HMAC/JWT для верификации входящих запросов. "
            "Пустая строка отключает проверку."
        ),
    )
    signature_header: str = Field(
        default="X-Signature",
        title="Заголовок подписи",
        description="Имя HTTP-заголовка, в котором приходит подпись",
        examples=["X-Hub-Signature-256", "X-Signature"],
    )


class BaseBotChannelSettings(BaseWebhookChannelSettings):
    """Канал бота: исходящие сообщения через bot-API.

    Универсальный контракт для bot-каналов (Express BotX, Telegram
    Bot API, Slack, и т.п.). Реализации задают свой ``base_url``,
    ``bot_id`` (или его аналог — ``token`` для Telegram, ``app_id``
    для Slack), ``secret_key``.

    Поля:
        bot_id: Идентификатор бота в системе (UUID для Express,
            числовой ID для Telegram перед двоеточием в токене).
        secret_key: Секретный ключ бота (для подписи JWT/HMAC при
            обращениях к bot-API). Для Telegram — часть после ":".
        base_url: Базовый URL bot-API (HTTP-сервиса мессенджера).
    """

    bot_id: str = Field(
        default="",
        title="ID бота",
        description="Идентификатор бота в системе мессенджера",
    )
    secret_key: str = Field(
        default="",
        title="Секретный ключ",
        description="Секрет для подписи запросов к bot-API",
    )
    base_url: str = Field(
        default="",
        title="Base URL",
        description="Базовый URL bot-API мессенджера",
        examples=["https://botx.corp.example.ru", "https://api.telegram.org"],
    )
