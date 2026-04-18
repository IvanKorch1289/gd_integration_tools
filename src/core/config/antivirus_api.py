from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("AntivirusAPISettings", "antivirus_api_settings")


class AntivirusAPISettings(BaseSettingsWithLoader):
    """Настройки интеграции с API антивирусной проверки файлов."""

    yaml_group: ClassVar[str] = "antivirus"
    model_config = SettingsConfigDict(env_prefix="ANTIVIRUS_", extra="forbid")

    # URL
    base_url: str = Field(
        ...,
        title="Базовый URL API",
        description="Базовый URL антивирусного API без пути конкретного метода",
        examples=["https://kkdrweb.bank.srv:443"],
    )

    endpoints: dict[str, str] = Field(
        ...,
        title="Эндпоинты API",
        description="Словарь относительных путей методов антивирусного API",
        examples=[{"SCAN_FILE": "/check/check"}],
    )

    # Multipart
    multipart_field_name: str | None = Field(
        default=None,
        title="Имя multipart-поля",
        description=(
            "Имя поля multipart/form-data для передачи файла. "
            "Если не указано, используется оригинальное имя файла."
        ),
        examples=["test.zip", "file"],
    )

    default_content_type: str = Field(
        default="application/octet-stream",
        title="Content-Type по умолчанию",
        min_length=1,
        description="Content-Type, используемый если тип файла не определён",
        examples=["application/octet-stream", "application/zip"],
    )

    default_headers: dict[str, str] = Field(
        default_factory=dict,
        title="Дополнительные заголовки",
        description="Статические заголовки для запросов к антивирусному API",
        examples=[{"X-Client-Id": "backend-service"}],
    )

    # Таймауты
    connect_timeout: float = Field(
        default=10.0,
        title="Таймаут подключения",
        ge=0.1,
        description="Максимальное время установки соединения с AV API",
        examples=[10.0],
    )

    read_timeout: float = Field(
        default=120.0,
        title="Таймаут чтения",
        ge=0.1,
        description="Максимальное время ожидания ответа от AV API",
        examples=[120.0],
    )

    total_timeout: float = Field(
        default=130.0,
        title="Общий таймаут запроса",
        ge=0.1,
        description="Полный лимит времени на запрос к AV API",
        examples=[130.0],
    )

    # Retry
    max_retries: int = Field(
        default=2,
        title="Количество повторов",
        ge=0,
        le=10,
        description="Количество повторных попыток при временных ошибках",
        examples=[2],
    )

    retry_backoff_factor: float = Field(
        default=1.0,
        title="Коэффициент backoff",
        ge=0.1,
        description="Множитель экспоненциальной задержки между retry",
        examples=[1.0, 2.0],
    )

    # Поведение
    raise_for_status: bool = Field(
        default=True,
        title="Поднимать исключение при HTTP-ошибке",
        description="Если true, HTTP-клиент вызывает raise_for_status()",
        examples=[True],
    )

    response_type: Literal["auto", "json", "text", "bytes"] = Field(
        default="auto",
        title="Тип разбора ответа",
        description="Режим обработки ответа антивирусного API",
        examples=["auto", "json", "text", "bytes"],
    )

    def build_url(self, endpoint_name: str) -> str:
        """
        Собирает полный URL по имени эндпоинта.
        """
        path = self.endpoints[endpoint_name]
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


antivirus_api_settings = AntivirusAPISettings()
"""Настройки интеграции с сервисом проверки антивирусом"""
