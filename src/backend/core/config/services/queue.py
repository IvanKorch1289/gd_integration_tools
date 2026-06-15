from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader


class QueueSettings(BaseSettingsWithLoader):
    """
    Настройки конфигурации для брокера сообщений.

    Этот класс содержит параметры для настройки подключения к брокеру сообщений (Kafka или RabbitMQ),
    а также параметры для управления соединениями и аутентификации.
    """

    yaml_group: ClassVar[str] = "queue"
    model_config = SettingsConfigDict(env_prefix="QUEUE_", extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "Включает интеграцию с брокером сообщений. На dev_light "
            "профиле может быть ``False`` — в этом случае FastStream "
            "router не создаётся и подписки на очереди пропускаются."
        ),
    )

    # Блок настроек типа и подключения к брокеру
    type: Literal["kafka", "rabbitmq"] = Field(
        ..., description="Тип брокера сообщений", json_schema_extra={"example": "kafka"}
    )
    host: str = Field(
        ..., description="Имя хоста брокера", json_schema_extra={"example": "broker.example.com"}
    )
    port: int = Field(..., ge=1, le=65535, description="Номер порта брокера")
    ui_port: int = Field(
        ..., ge=1, le=65535, description="Номер порта UI брокера", json_schema_extra={"example": 9121}
    )

    # Блок настроек таймаутов и повторных подключений
    timeout: int = Field(
        ...,
        ge=5,
        le=300,
        description="Таймаут подключения к брокеру в секундах",
        json_schema_extra={"example": 30},
    )
    reconnect_interval: int = Field(
        ...,
        ge=5,
        le=300,
        description="Интервал между попытками повторного подключения в секундах",
        json_schema_extra={"example": 60},
    )

    # Блок настроек потребителей и graceful shutdown
    max_consumers: int = Field(
        ...,
        ge=1,
        description="Максимальное количество экземпляров потребителей",
        json_schema_extra={"example": 10},
    )
    graceful_timeout: int = Field(
        ...,
        ge=5,
        le=300,
        description="Таймаут graceful shutdown в секундах",
        json_schema_extra={"example": 60},
    )

    # Блок настроек SSL/TLS и аутентификации
    use_ssl: bool = Field(
        ..., description="Включить SSL/TLS для безопасных соединений", json_schema_extra={"example": True}
    )
    ca_bundle: Path | None = Field(
        ..., description="Путь к файлу CA сертификата", json_schema_extra={"example": "/path/to/ca.pem"}
    )
    username: str | None = Field(
        ..., description="Имя пользователя для аутентификации", json_schema_extra={"example": "kafka-user"}
    )
    password: str | None = Field(
        ..., description="Пароль для аутентификации", json_schema_extra={"example": "securepassword123"}
    )

    # Блок настроек топиков
    queues: list[dict[str, str]] = Field(
        ...,
        min_length=1,
        description="Список топиков",
        json_schema_extra={
            "example": [
                {"name": "queue1", "value": "creating-queue"},
                {"name": "queue2", "value": "updating-queue"},
            ],
        },
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int, values: Any) -> int:
        """Валидатор: порт 465 требует SSL/TLS."""
        if v == 465 and not values.data.get("use_tls"):
            raise ValueError("Порт 465 требует включения SSL/TLS")
        return v

    @field_validator("ca_bundle")
    @classmethod
    def validate_ca_path(cls, v: Path | None) -> Path | None:
        """Валидатор: ``ca_bundle`` path должен существовать (если указан)."""
        if v and not v.exists():
            raise ValueError(f"Файл CA bundle не найден: {v}")
        return v

    @computed_field(description="Сформировать URL для подключения к очереди")
    def queue_url(self) -> str:
        """Сформировать URL для подключения к очереди."""
        return f"amqp://{self.username}:{self.password}@{self.host}:{self.port}/"

    @computed_field(description="Сформировать URL для подключения к UI очереди")
    def queue_ui_url(self) -> str:
        """Сформировать URL для подключения к UI очереди."""
        return f"{self.host}:{self.ui_port}"

    def get_queue_name(self, queue_key: str) -> str:
        """Возвращает имя AMQP-queue по его ключу.

        Args:
            queue_key: Ключ (например, ``"orders"``).

        Returns:
            Имя queue (``self.queues[i]["name"]``) или ``None``.
        """
        # Оптимизированный поиск с использованием генератора
        queue = next(
            (queue for queue in self.queues if queue.get("name", None) == queue_key),
            None,
        )

        if not queue:
            raise ValueError(f"Не настроен топик для ключа: {queue_key}")

        return queue["value"]


class TasksSettings(BaseSettingsWithLoader):
    """
    Настройки конфигурации для очереди задач и управления воркерами.

    Этот класс содержит параметры для настройки максимального количества попыток выполнения задач,
    задержек, таймаутов и других параметров, связанных с обработкой задач.
    """

    yaml_group: ClassVar[str] = "tasks"
    model_config = SettingsConfigDict(env_prefix="TASKS_", extra="forbid")

    # Блок настроек для задач
    task_max_attempts: int = Field(
        ..., description="Максимальное количество попыток выполнения задачи", json_schema_extra={"example": 5}
    )
    task_seconds_delay: int = Field(
        ..., description="Начальная задержка в секундах для задачи", json_schema_extra={"example": 60}
    )
    task_retry_jitter_factor: float = Field(
        ..., description="Фактор случайности для экспоненциального отката", json_schema_extra={"example": 0.5}
    )
    task_timeout_seconds: int = Field(
        ..., description="Максимальное время выполнения задачи в секундах", json_schema_extra={"example": 3600}
    )

    # Блок настроек для потоков (flows)
    flow_max_attempts: int = Field(
        ..., description="Максимальное количество попыток выполнения потока", json_schema_extra={"example": 5}
    )
    flow_seconds_delay: int = Field(
        ..., description="Начальная задержка в секундах для потока", json_schema_extra={"example": 60}
    )
    flow_retry_jitter_factor: float = Field(
        ..., description="Фактор случайности для экспоненциального отката", json_schema_extra={"example": 0.5}
    )
    flow_timeout_seconds: int = Field(
        ..., description="Максимальное время выполнения потока в секундах", json_schema_extra={"example": 3600}
    )


class GRPCSettings(BaseSettingsWithLoader):
    """
    Настройки конфигурации для gRPC сервисов.

    Этот класс содержит параметры для настройки пути к сокету и максимального количества воркеров.
    """

    yaml_group: ClassVar[str] = "grpc"
    model_config = SettingsConfigDict(env_prefix="GRPC_", extra="forbid")

    # Блок настроек сокета и воркеров
    socket_path: str = Field(..., description="Путь к файлу сокета gRPC")
    max_workers: int = Field(
        ..., description="Максимальное количество процессов воркеров gRPC", json_schema_extra={"example": 10}
    )

    # TLS / mTLS (ADR-004). Для dev/unix-socket TLS может быть отключён.
    tls_enabled: bool = Field(
        default=False,
        description="Включить TLS для gRPC (обязательно в prod для TCP-портов)",
    )
    server_cert_path: str = Field(
        default="", description="Путь к серверному сертификату (PEM)"
    )
    server_key_path: str = Field(
        default="", description="Путь к приватному ключу сервера (PEM)"
    )
    ca_cert_path: str = Field(
        default="", description="Путь к CA-сертификату для mTLS (опционально)"
    )
    require_client_auth: bool = Field(
        default=False, description="Требовать клиентский сертификат (mTLS)"
    )

    @computed_field(description="Сформировать URI для подключения к сокету")
    def socket_uri(self) -> str:
        """Сформировать URI для подключения к сокету."""
        return f"unix://{self.socket_path}"


queue_settings = QueueSettings()
"""Глобальные настройки подключения к очереди сообщений"""

tasks_settings = TasksSettings()
"""Глобальные настройки фоновых задач"""

grpc_settings = GRPCSettings()
"""Глобальные настройки GRPC-сервера"""
