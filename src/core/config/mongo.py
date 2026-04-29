"""Настройки подключения к MongoDB.

Выделено из ``core/config/database.py`` для разделения SQL/NoSQL слоёв
конфигурации (Wave 8.4 / pre-Wave 9 подготовка).
"""

from typing import ClassVar

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("MongoConnectionSettings", "mongo_connection_settings")


class MongoConnectionSettings(BaseSettingsWithLoader):
    """Настройки подключения к MongoDB.

    Содержит параметры для работы с MongoDB, включая настройки пула соединений.
    """

    yaml_group: ClassVar[str] = "mongo"
    model_config = SettingsConfigDict(env_prefix="MONGO_", extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "Включить интеграцию с MongoDB. Для dev_light устанавливается "
            "``false`` через ``config_profiles/dev_light.yml``."
        ),
    )

    username: str = Field(
        ...,
        title="Пользователь",
        description="Имя пользователя с правами на базу",
        examples=["mongo_admin"],
    )

    password: str = Field(
        ...,
        title="Пароль",
        min_length=8,
        description="Пароль для аутентификации в MongoDB",
        examples=["M0ng0Pa$$w0rd"],
    )

    name: str = Field(
        ...,
        title="База данных",
        description="Наименование базы данных, к которой будет осуществляться подключение",
        examples=["myapp_prod", "mydb"],
    )

    host: str = Field(
        ..., title="Хост", description="Сервер MongoDB", examples=["mongo.example.com"]
    )

    port: int = Field(
        ...,
        title="Порт",
        ge=1,
        le=65535,
        description="Порт для подключения к MongoDB",
        examples=[27017],
    )

    min_pool_size: int = Field(
        ...,
        title="Мин. размер пула",
        ge=1,
        le=500,
        description="Минимальное количество соединений в пуле",
        examples=[50],
    )

    max_pool_size: int = Field(
        ...,
        title="Макс. размер пула",
        ge=1,
        le=500,
        description="Максимальное количество соединений в пуле",
        examples=[100],
    )

    timeout: int = Field(
        ...,
        title="Таймаут",
        description="Время ожидания подключения (миллисекунды)",
        examples=[5000],
    )

    @computed_field(description="Строка подключения MongoDB")
    def connection_string(self) -> str:
        """Формирует полную строку подключения с аутентификацией."""
        return (
            f"mongodb://{self.username}:{self.password}@"
            f"{self.host}:{self.port}/{self.name}?authSource=admin"
        )


mongo_connection_settings = MongoConnectionSettings()
"""Глобальные настройки MongoDB."""
