"""ЧАСТЬ D — типизация секретов как ``SecretStr`` (ADR-0375, wave 14).

CF3 (ADR-0373) типизировал ``database.py`` и ``mongo.py``. Эта волна
закрывает остальные реально секретные поля конфигурации и проверяет, что:

* значение секрета не попадает в ``repr`` модели;
* публичные контракты НЕ сломаны: поля, которые отдаются наружу как
  строка (DSN, ``AuthConfig.api_key``, ``redis_url``), остаются строками;
* «пустой» секрет по-прежнему считается отсутствующим (consumers проверяют
  ``if not api_key`` перед использованием).

Поля-«исключения» (owner-задачи) перечислены в ADR-0375.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.backend.core.config.ai import (
    GigaChatSettings,
    HuggingFaceSettings,
    MiniMaxSettings,
    NimSettings,
    OpenAISettings,
    OpenRouterSettings,
    OpenWebUISettings,
    PerplexitySettings,
    SaluteSpeechSettings,
    YandexGPTSettings,
)
from src.backend.core.config.influxdb import InfluxDBSettings
from src.backend.core.config.lineage import LineageSettings
from src.backend.core.config.rag import RAGSettings
from src.backend.core.config.secret import secret_value
from src.backend.core.config.security import SecureSettings
from src.backend.core.config.services.cache import RedisSettings
from src.backend.core.config.services.jupyter_hub import JupyterHubSettings
from src.backend.core.config.services.ldap import LdapSettings
from src.backend.core.config.services.mail import MailSettings
from src.backend.core.config.services.storage import FileStorageSettings

pytestmark = pytest.mark.unit

#: Поля, типизированные как ``SecretStr`` в этой волне.
TYPED_SECRET_FIELDS: tuple[tuple[type, str], ...] = (
    (SecureSettings, "secret_key"),
    (SecureSettings, "api_key"),
    (PerplexitySettings, "api_key"),
    (HuggingFaceSettings, "api_key"),
    (OpenWebUISettings, "api_key"),
    (OpenRouterSettings, "api_key"),
    (NimSettings, "api_key"),
    (OpenAISettings, "api_key"),
    (MiniMaxSettings, "api_key"),
    (YandexGPTSettings, "api_key"),
    (GigaChatSettings, "credentials"),
    (SaluteSpeechSettings, "credentials"),
    (MailSettings, "password"),
    (FileStorageSettings, "access_key"),
    (FileStorageSettings, "secret_key"),
    (LdapSettings, "bind_password"),
    (LineageSettings, "auth_token"),
    (InfluxDBSettings, "token"),
    (JupyterHubSettings, "api_token"),
    (RAGSettings, "qdrant_api_key"),
    (RAGSettings, "embedding_api_key"),
    (RedisSettings, "password"),
    (RedisSettings, "sentinel_password"),
)


def _instance(model_cls: type, **overrides: object) -> object:
    """Создаёт экземпляр модели со всеми полями (для ``repr``).

    ``model_construct`` не подставляет значения для обязательных полей —
    без этого ``repr`` падает с ``AttributeError``.

    Args:
        model_cls: Класс модели.
        **overrides: Значения полей, которые нужно задать явно.

    Returns:
        Экземпляр модели.
    """
    base = model_cls.model_construct()
    data: dict[str, object] = {}
    for name in model_cls.model_fields:
        try:
            data[name] = getattr(base, name)
        except AttributeError:
            data[name] = None
    data.update(overrides)
    return model_cls.model_construct(**data)


class TestSecretFieldsAreTyped:
    """Поля-секреты типизированы как ``SecretStr``."""

    @pytest.mark.parametrize(
        ("model_cls", "field_name"),
        TYPED_SECRET_FIELDS,
        ids=[f"{m.__name__}.{f}" for m, f in TYPED_SECRET_FIELDS],
    )
    def test_field_annotation_is_secret_str(
        self, model_cls: type, field_name: str
    ) -> None:
        """Аннотация поля содержит ``SecretStr``."""
        annotation = model_cls.model_fields[field_name].annotation
        assert "SecretStr" in str(annotation), (
            f"{model_cls.__name__}.{field_name}: {annotation}"
        )

    @pytest.mark.parametrize(
        ("model_cls", "field_name"),
        TYPED_SECRET_FIELDS,
        ids=[f"{m.__name__}.{f}" for m, f in TYPED_SECRET_FIELDS],
    )
    def test_secret_is_masked_in_repr(
        self, model_cls: type, field_name: str
    ) -> None:
        """Значение секрета не попадает в ``repr`` модели."""
        instance = _instance(model_cls, **{field_name: SecretStr("s3cr3t-value")})
        assert "s3cr3t-value" not in repr(instance)


class TestSecretValueHelper:
    """Хелпер ``secret_value`` извлекает «сырое» значение."""

    def test_extracts_from_secret_str(self) -> None:
        """``SecretStr`` → строка с реальным значением."""
        assert secret_value(SecretStr("s3cr3t")) == "s3cr3t"

    def test_none_becomes_empty_string(self) -> None:
        """``None`` → пустая строка (значит «секрет не задан»)."""
        assert secret_value(None) == ""

    def test_plain_string_passthrough(self) -> None:
        """Обычная строка проходит без изменений (нетипизированные поля)."""
        assert secret_value("plain") == "plain"

    def test_empty_secret_is_falsy(self) -> None:
        """Пустой секрет остаётся «незаданным» для потребителей."""
        assert not secret_value(SecretStr(""))


class TestPublicContractsPreserved:
    """Публичные контракты (строковый выход) не сломаны."""

    def test_auth_config_returns_plain_strings(self) -> None:
        """``build_auth_config`` отдаёт ``str`` (не ``SecretStr``)."""
        from src.backend.core.config.auth import build_auth_config

        secure = SecureSettings.model_construct(
            secret_key=SecretStr("s" * 32),
            api_key=SecretStr("ak-plain"),
            algorithm="HS256",
            token_lifetime=3600,
        )
        cfg = build_auth_config(secure=secure, express=None)
        assert cfg.api_key == "ak-plain"
        assert isinstance(cfg.api_key, str)
        assert cfg.jwt.secret_key == "s" * 32
        assert isinstance(cfg.jwt.secret_key, str)

    def test_storage_has_credentials_still_works(self) -> None:
        """``FileStorageSettings.has_credentials`` работает с ``SecretStr``."""
        settings = FileStorageSettings.model_construct(
            access_key=SecretStr("AKIA"),
            secret_key=SecretStr("secret"),
        )
        assert settings.has_credentials() is True

        empty = FileStorageSettings.model_construct(
            access_key=SecretStr(""), secret_key=SecretStr("secret")
        )
        assert empty.has_credentials() is False

    def test_redis_url_contains_plain_password(self) -> None:
        """``redis_url`` (публичный computed field) содержит пароль строкой."""
        settings = RedisSettings.model_construct(
            host="redis.example.com",
            port=6379,
            use_ssl=False,
            password=SecretStr("redis-pass"),
        )
        assert ":redis-pass@" in settings.redis_url

    def test_mail_password_is_empty_by_default(self) -> None:
        """Пустой пароль SMTP остаётся «нет auth» (поведение не изменилось)."""
        settings = MailSettings.model_construct(password=SecretStr(""))
        assert not secret_value(settings.password)
