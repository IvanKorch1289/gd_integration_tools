import os
from typing import Any, ClassVar, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("SecureSettings", "secure_settings")


class SecureSettings(BaseSettingsWithLoader):
    """Конфигурация системы аутентификации и авторизации.

    Содержит параметры безопасности для работы с токенами, API-ключами,
    настройками Cookie и механизмами защиты от атак.
    """

    yaml_group: ClassVar[str] = "security"
    model_config = SettingsConfigDict(env_prefix="SEC_", extra="forbid")

    # Основные настройки токенов
    token_lifetime: int = Field(
        ...,
        ge=60,
        description="Время жизни токена в секундах (минимум 60)",
        examples=[3600, 86400],
    )
    refresh_token_lifetime: int = Field(
        ...,
        ge=3600,
        description="Время жизни refresh-токена в секундах (по умолчанию 30 дней)",
        examples=[2592000, 86400],
    )

    # Алгоритмы и криптография
    secret_key: str = Field(
        ...,
        min_length=32,
        description="Секретный ключ для подписи токенов (минимум 32 символа)",
        examples=["supersecretkeywithatleast32characters123"],
    )
    algorithm: Literal["HS256", "HS384", "HS512", "RS256"] = Field(
        ..., description="Алгоритм подписи токенов", examples=["HS256", "RS256"]
    )

    # Wave [s2/k1-2-jwt-jwks]: JWKS-кеш для асимметричных алгоритмов (RS256/ES256).
    # Если URL не задан — backend работает только с симметричными алгоритмами.
    jwks_url: str = Field(
        default="",
        description=(
            "URL JWKS endpoint'а IdP для асимметричной верификации JWT. "
            "Пустая строка отключает JWKS-кеш."
        ),
        examples=["https://auth.example.com/.well-known/jwks.json"],
    )
    jwks_cache_ttl: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="TTL JWKS-кеша в секундах (по умолчанию 5 минут).",
    )
    jwks_fetch_timeout: float = Field(
        default=5.0,
        gt=0.0,
        le=60.0,
        description="HTTP-таймаут для fetch JWKS-документа (сек).",
    )
    jwt_leeway: int = Field(
        default=60,
        ge=0,
        le=600,
        description="Допустимое отклонение exp/nbf в секундах.",
    )
    jwt_blacklist_enabled: bool = Field(default=False)

    # API-безопасность
    api_key: str = Field(
        ..., description="Основной API-ключ приложения", examples=["your_api_key_123"]
    )
    allowed_hosts: list[str] = Field(
        ...,
        description="Разрешенные хосты для входящих запросов",
        examples=["example.com", "api.example.com"],
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description=(
            "CORS allow-origins whitelist. В prod-окружении запрещён '*' — "
            "список должен быть явным."
        ),
        examples=[["https://app.example.com", "https://admin.example.com"]],
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Разрешить отправку cookies/auth headers в cross-origin запросах",
    )
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        description="Разрешённые HTTP-методы для cross-origin",
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: [
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-API-Key",
        ],
        description="Разрешённые заголовки для cross-origin",
    )

    @field_validator("cors_origins")
    @classmethod
    def _forbid_wildcard_in_prod(cls, value: list[str]) -> list[str]:
        """В prod-окружении запрещён '*' — требуется явный whitelist.

        cycle-9/D-AUDIT-902 fix: canonical env var — APP_ENVIRONMENT.
        Старые APP_ENV / ENVIRONMENT оставлены для backward-compat;
        при их использовании эмитится DeprecationWarning (cycle-10
        планирует их полное удаление).
        """
        import warnings as _warnings

        legacy_app_env = os.getenv("APP_ENV")
        legacy_environment = os.getenv("ENVIRONMENT")
        env = os.getenv("APP_ENVIRONMENT")
        if env is None:
            if legacy_app_env is not None or legacy_environment is not None:
                _warnings.warn(
                    "APP_ENV/ENVIRONMENT deprecated; use APP_ENVIRONMENT "
                    "instead. Удаление в cycle-10.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                env = legacy_app_env or legacy_environment or "dev"
            else:
                env = "dev"
        if env.lower() in {"prod", "production"} and "*" in value:
            raise ValueError(
                "CORS wildcard '*' запрещён в prod. Укажите явный список origin."
            )
        return value

    @model_validator(mode="after")
    def _forbid_wildcard_with_credentials(self) -> SecureSettings:
        """Cycle 25 S1: never allow wildcard origin WITH credentials enabled.

        Browsers reject this combination, but misconfiguration can leak
        credentials via CSRF. Block at model-level (not just diagnostic).
        """
        if "*" in self.cors_origins and self.cors_allow_credentials:
            raise ValueError(
                "CORS misconfiguration: wildcard origin '*' combined with "
                "credentials=True is forbidden. Specify explicit origins or "
                "disable credentials."
            )
        return self

    routes_without_api_key: list[str] = Field(
        ...,
        description="Эндпоинты, доступные без API-ключа",
        examples=["/health", "/status"],
    )
    admin_ips: set[str] = Field(
        ...,
        description="IP-адреса, из которых разрешен доступ к административным эндпоинтам'",
        examples=["127.0.0.1", "192.168.0.1"],
    )
    admin_routes: set[str] = Field(
        ...,
        description="Эндпоинты, доступные только для администраторов",
        examples=["/admin/users", "/admin/logs"],
    )
    # P0 (cycle 7, production-grade plan): admin роли для API key holder.
    # Раньше был hardcoded в api_key.py:107-115. Сейчас configurable per-deployment
    # (default сохранён для backward-compat). Позволяет тонко настраивать
    # security model (например, в production только super_admin, в dev — все).
    api_key_admin_roles: list[str] = Field(
        default_factory=lambda: ["operator", "super_admin"],
        description=(
            "Admin роли, автоматически grant'имые любому валидному API key "
            "holder. Default ['operator', 'super_admin'] сохраняет pre-fix "
            "поведение. Production может сузить до ['super_admin'] для "
            "hardening. Env: comma-separated (SEC_API_KEY_ADMIN_ROLES=super_admin,admin)."
        ),
        examples=[["super_admin"], ["operator", "super_admin", "tenant_admin"]],
    )

    @field_validator("api_key_admin_roles", mode="before")
    @classmethod
    def _parse_api_key_admin_roles(cls, value: Any) -> list[str]:
        """Парсинг comma-separated string из env (P0 cycle 7).

        Pydantic-settings v2 не парсит list из comma-separated автоматически;
        принимает только JSON (например ``'["operator"]'``). Этот validator
        позволяет удобный ``SEC_API_KEY_ADMIN_ROLES=super_admin,admin``.
        """
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return value

    # Защита от атак и лимиты
    request_timeout: float = Field(
        ...,
        description="Максимальное время обработки запроса (секунды)",
        examples=[5.0, 10.0],
    )
    rate_limit: int = Field(
        ..., description="Лимит запросов в минуту для приложения", examples=[100, 500]
    )
    rate_time_measure_seconds: int = Field(
        ...,
        description="Временное окно для ограничения запросов (секунды)",
        examples=[60, 300],
    )

    # V9 (S183 W4): HMAC-секреты для входящих webhooks. Ключ — prefix пути
    # (например "/webhooks/stripe"), значение — shared secret отправителя.
    # Пустой dict отключает WebhookSignatureMiddleware в prod (безопасный default).
    webhook_signature_secrets: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Маппинг prefix пути → HMAC-секрет для WebhookSignatureMiddleware. "
            "Пустой словарь — middleware не проверяет подпись (только для dev)."
        ),
        examples=[{"/webhooks/stripe": "whsec_xxx"}],
    )
    # Fail-closed при отсутствии секрета для protected prefix (default ON).
    # Если True и path матчит prefix, но соответствующий секрет не сконфигурирован —
    # middleware возвращает 503 вместо пропуска без проверки. Safe-by-default;
    # отключать только явно для dev/test, где вебхуки без подписи — штатный кейс.
    webhook_signature_fail_closed: bool = Field(
        default=True,
        description=(
            "Fail-closed для protected prefix без сконфигурированного секрета. "
            "True = 503 при missing secret (рекомендуется для prod). "
            "False = skip-verify с debug-логом (только dev/test)."
        ),
        examples=[True, False],
    )

    # S204 retro-audit C-NEW-7: allowlist для MCP stdio-серверов.
    # ``LocalMCPClient.connect_stdio`` запускает subprocess по ``command[0]`` —
    # без allowlist это RCE-поверхность. Список содержит абсолютные пути или
    # имена в PATH. Пустой список = deny all (безопасный default).
    mcp_stdio_allowed_commands: list[str] = Field(
        default_factory=list,
        description=(
            "Allowlist исполняемых файлов для LocalMCPClient.connect_stdio. "
            "Пустой список запрещает любые stdio-MCP-серверы (fail-closed)."
        ),
        examples=["/usr/local/bin/mcp-filesystem", "/opt/mcp/servers/git-server"],
    )

    # S204 retro-audit C-NEW-2: inline notebook-content — RCE-поверхность
    # (произвольный Python в JupyterHub kernel). Default False = deny;
    # admin явным образом включает только если доверяет всем callers с
    # capability ``jupyter.hub.run``. Registry-based notebooks остаются
    # доступными (они проходят ревью при регистрации).
    jupyter_inline_content_enabled: bool = Field(
        default=False,
        description=(
            "Разрешить передачу .ipynb содержимого inline "
            "(notebook_content / notebook_content_b64). Default False — "
            "только registry-based notebooks. Включать только после "
            "явной оценки RCE-риска для всех callers."
        ),
    )


secure_settings = SecureSettings()
"""Глобальные настройки безопасности"""
