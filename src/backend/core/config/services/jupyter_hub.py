"""JupyterHub connection settings (TD-024).

Pydantic-settings для JupyterHub REST API client.
Yaml-группа: ``jupyter_hub`` (settings.yaml → ``jupyter_hub: { ... }``).
Env-префикс: ``JUPYTER_HUB_`` (env vars → ``JUPYTER_HUB_BASE_URL=...``).

Секреты:
    * ``api_token`` — JupyterHub API token (service или user).
      В production брать из Vault / sealed-secrets, НЕ из env vars.

Архитектура:
    * ``JupyterHubSettings`` — конфигурация (эта модель).
    * ``JupyterHubClient`` — async HTTP фасад (см.
      :mod:`src.backend.infrastructure.clients.external.jupyter_hub`).
    * Feature-flag ``jupyter_hub_enabled`` (default OFF) — caller обязан
      проверять ПЕРЕД инстанцированием client.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("JupyterHubSettings", "jupyter_hub_settings")

# ── Defaults (single source of truth for magic numbers) ──
_DEFAULT_BASE_URL: str = "http://localhost:8000"
_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_DEFAULT_CONNECT_TIMEOUT: float = 10.0
_DEFAULT_MAX_RETRIES: int = 3
_DEFAULT_RETRY_BACKOFF_FACTOR: float = 0.5
_DEFAULT_RETRY_STATUS_CODES: tuple[int, ...] = (408, 429, 500, 502, 503, 504)
_DEFAULT_KERNEL: str = "python3"


class JupyterHubSettings(BaseSettingsWithLoader):
    """Pydantic-settings для JupyterHub API server.

    Yaml-группа: ``jupyter_hub``.
    Env-префикс: ``JUPYTER_HUB_``.
    """

    yaml_group: ClassVar[str] = "jupyter_hub"  # type: ignore[misc]
    model_config = SettingsConfigDict(env_prefix="JUPYTER_HUB_", extra="forbid")

    # ── Обязательные параметры (при enabled=True) ──

    enabled: bool = Field(
        default=False,
        description="Включить интеграцию с JupyterHub.",
    )

    base_url: str = Field(
        default=_DEFAULT_BASE_URL,
        description="Базовый URL JupyterHub (без trailing slash).",
        examples=["http://localhost:8000", "https://jupyter.corp.example.ru"],
    )

    api_token: str = Field(
        default="",
        description=(
            "JupyterHub API token (service или user). "
            "В production — из Vault / sealed-secrets."
        ),
    )

    # ── HTTP tuning (без магических чисел) ──

    timeout_seconds: float = Field(
        default=_DEFAULT_TIMEOUT_SECONDS,
        gt=0.0,
        le=300.0,
        description="Общий таймаут HTTP-запроса (сек).",
    )

    connect_timeout: float = Field(
        default=_DEFAULT_CONNECT_TIMEOUT,
        gt=0.0,
        le=120.0,
        description="Таймаут установки TCP-соединения (сек).",
    )

    max_retries: int = Field(
        default=_DEFAULT_MAX_RETRIES,
        ge=0,
        le=10,
        description="Максимальное число retry-попыток при retriable ошибках.",
    )

    retry_backoff_factor: float = Field(
        default=_DEFAULT_RETRY_BACKOFF_FACTOR,
        ge=0.0,
        le=60.0,
        description="Множитель exponential backoff между retry (сек).",
    )

    retry_status_codes: tuple[int, ...] = Field(
        default=_DEFAULT_RETRY_STATUS_CODES,
        description="HTTP-статусы, при которых выполняется retry.",
    )

    ssl_verify: bool = Field(
        default=True,
        description="Проверять TLS-сертификат сервера.",
    )

    # ── Jupyter-специфичные параметры ──

    default_kernel: str = Field(
        default=_DEFAULT_KERNEL,
        description="Имя kernel по умолчанию для spawn.",
        examples=["python3", "ir", "scala"],
    )

    notebook_dir: str = Field(
        default="",
        description=(
            "Рабочая директория для notebooks (относительно hub). "
            "Пустая строка — использовать server default."
        ),
    )

    # ── Валидация ──

    @model_validator(mode="after")
    def check_token_when_enabled(self) -> "JupyterHubSettings":
        """Если enabled=True — api_token должен быть задан."""
        if self.enabled and not self.api_token:
            raise ValueError("api_token обязателен при enabled=true")
        return self


# Глобальный экземпляр (lazy-load через BaseSettingsWithLoader).
jupyter_hub_settings: JupyterHubSettings = JupyterHubSettings()  # type: ignore[call-arg]
