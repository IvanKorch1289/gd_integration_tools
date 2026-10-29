"""ЧАСТЬ D — типизация секретов как ``SecretStr`` (ADR-0375, wave 14).

CF3 (ADR-0373) типизировал ``database.py`` и ``mongo.py``. Эта волна
закрывает остальные реально секретные поля конфигурации и проверяет, что:

* значение секрета не попадает в ``repr`` модели;
* публичные контракты НЕ сломаны: поля, которые отдаются наружу как
  строка (DSN, ``AuthConfig.api_key``, ``redis_url``), остаются строками;
* «пустой» секрет по-прежнему считается отсутствующим (consumers проверяют
  ``if not api_key`` перед использованием).

Поля-«исключения» (owner-задачи) перечислены в ADR-0375.

ADR-0378 (wave 15, кластер W3) добавляет сюда проверки маскирования:
``repr=False`` у computed-поля НЕ маскирует значение в ``model_dump()``,
поэтому DSN/URL с паролем протекали в дампы и в логи старта.
"""

from __future__ import annotations

from types import SimpleNamespace

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
from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.influxdb import InfluxDBSettings
from src.backend.core.config.lineage import LineageSettings
from src.backend.core.config.mongo import MongoConnectionSettings
from src.backend.core.config.rag import RAGSettings
from src.backend.core.config.secret import secret_value
from src.backend.core.config.security import SecureSettings
from src.backend.core.config.services.cache import RedisSettings
from src.backend.core.config.services.jupyter_hub import JupyterHubSettings
from src.backend.core.config.services.ldap import LdapSettings
from src.backend.core.config.services.mail import MailSettings
from src.backend.core.config.services.storage import FileStorageSettings

pytestmark = pytest.mark.unit

#: Значения для полной валидации моделей подключений.
_DB_VALUES: dict[str, object] = {
    "type": "postgresql",
    "host": "db.example.com",
    "port": 5432,
    "name": "app",
    "username": "app_user",
    "password": "s3cr3t-db-pass",
    "pool_size": 10,
    "max_overflow": 10,
    "pool_recycle": 1800,
    "pool_timeout": 30,
    "connect_timeout": 10,
    "command_timeout": 30,
    "max_retries": 0,
    "circuit_breaker_max_failures": 10,
    "circuit_breaker_reset_timeout": 30,
    "slow_query_threshold": 1.0,
}

_MONGO_VALUES: dict[str, object] = {
    "username": "mongo_admin",
    "password": "s3cr3t-mongo-pass",
    "name": "app",
    "host": "mongo.example.com",
    "port": 27017,
    "min_pool_size": 10,
    "max_pool_size": 50,
    "timeout": 5000,
}

#: Пароль Redis из пробы независимого свипа (волна 15).
REDIS_SECRET = "REDISPASS-SECRET-1"
REDIS_REAL_URL = f"redis://:{REDIS_SECRET}@redis.local:6379"
REDIS_MASKED_URL = "redis://:***@redis.local:6379"

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


def _redis_settings() -> RedisSettings:
    """Экземпляр ``RedisSettings`` с паролем (все поля проставлены)."""
    return _instance(
        RedisSettings,
        host="redis.local",
        port=6379,
        use_ssl=False,
        password=SecretStr(REDIS_SECRET),
    )


class TestComputedFieldMasking:
    """Секреты в computed-полях не попадают в ``model_dump`` (ADR-0378).

    ``computed_field(repr=False)`` влияет только на ``__repr__`` — значение
    оставалось plain-строкой в ``model_dump()``/``model_dump_json()``.
    """

    def test_redis_url_masked_in_model_dump(self) -> None:
        """Пароль Redis замаскирован в дампе модели."""
        dumped = _redis_settings().model_dump()
        assert dumped["redis_url"] == REDIS_MASKED_URL

    def test_redis_url_masked_in_model_dump_json(self) -> None:
        """Пароль Redis не попадает в JSON-дамп модели."""
        assert REDIS_SECRET not in _redis_settings().model_dump_json()

    def test_redis_url_keeps_real_password_for_connection(self) -> None:
        """Атрибут ``redis_url`` остаётся рабочим (клиент подключается)."""
        assert _redis_settings().redis_url == REDIS_REAL_URL

    def test_redis_masked_url_property(self) -> None:
        """``redis_url_masked`` — URL с паролем ``***`` (для логов)."""
        assert _redis_settings().redis_url_masked == REDIS_MASKED_URL

    def test_database_dsn_masked_in_model_dump(self) -> None:
        """DSN реляционной БД замаскированы в дампе модели."""
        settings = DatabaseConnectionSettings.model_validate(_DB_VALUES)
        dumped = settings.model_dump()
        assert dumped["async_connection_url"] == (
            "postgresql+asyncpg://app_user:***@db.example.com:5432/app"
        )
        assert dumped["sync_connection_url"] == (
            "postgresql+psycopg://app_user:***@db.example.com:5432/app"
        )
        assert "s3cr3t-db-pass" not in settings.model_dump_json()

    def test_database_dsn_keeps_real_password_for_connection(self) -> None:
        """Атрибуты DSN остаются рабочими (SQLAlchemy подключается)."""
        settings = DatabaseConnectionSettings.model_validate(_DB_VALUES)
        assert "s3cr3t-db-pass" in settings.async_connection_url
        assert "s3cr3t-db-pass" in settings.sync_connection_url

    def test_mongo_connection_string_masked_in_model_dump(self) -> None:
        """Строка подключения MongoDB замаскирована в дампе модели."""
        settings = MongoConnectionSettings.model_validate(_MONGO_VALUES)
        dumped = settings.model_dump()
        assert dumped["connection_string"] == (
            "mongodb://mongo_admin:***@mongo.example.com:27017/app?authSource=admin"
        )
        assert "s3cr3t-mongo-pass" not in settings.model_dump_json()

    def test_mongo_connection_string_keeps_real_password_for_connection(self) -> None:
        """Атрибут ``connection_string`` остаётся рабочим (драйвер подключается)."""
        settings = MongoConnectionSettings.model_validate(_MONGO_VALUES)
        assert "s3cr3t-mongo-pass" in settings.connection_string


class TestWebhookSignatureSecretsMasking:
    """HMAC-ключи вебхуков не текут в ``repr``/``model_dump`` (ADR-0378)."""

    def test_secrets_not_leaked_in_repr(self) -> None:
        """Значения HMAC-ключей не попадают в ``repr`` модели."""
        settings = _instance(
            SecureSettings,
            webhook_signature_secrets={"/webhooks/stripe": "whsec_super-secret"},
        )
        assert "whsec_super-secret" not in repr(settings)

    def test_secrets_masked_in_model_dump(self) -> None:
        """Значения HMAC-ключей замаскированы в дампе модели."""
        settings = _instance(
            SecureSettings,
            webhook_signature_secrets={"/webhooks/stripe": "whsec_super-secret"},
        )
        dumped = settings.model_dump()
        assert dumped["webhook_signature_secrets"] == {"/webhooks/stripe": "***"}
        assert "whsec_super-secret" not in settings.model_dump_json()

    def test_runtime_values_unchanged(self) -> None:
        """Маппинг для middleware остаётся обычным ``dict[str, str]``."""
        settings = _instance(
            SecureSettings,
            webhook_signature_secrets={"/webhooks/stripe": "whsec_super-secret"},
        )
        secrets = settings.webhook_signature_secrets
        assert secrets == {"/webhooks/stripe": "whsec_super-secret"}
        assert isinstance(secrets["/webhooks/stripe"], str)


class TestEventBusStartupLogging:
    """Пароль Redis не утекает в лог старта (ADR-0378)."""

    async def test_redis_password_not_leaked_to_startup_logs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """INFO/ warning старта содержат замаскированный URL."""
        from src.backend.plugins.composition.lifecycle import startup

        records: list[str] = []

        class _FakeLogger:
            """Минимальный логгер: собирает отформатированные сообщения."""

            def info(self, msg: str, *args: object) -> None:
                """Записывает INFO-сообщение."""
                records.append(msg % args if args else msg)

            def warning(self, msg: str, *args: object) -> None:
                """Записывает WARNING-сообщение."""
                records.append(msg % args if args else msg)

        class _FakeBus:
            """EventBus-заглушка: запоминает URL подключения."""

            def __init__(self) -> None:
                self.started_with: str | None = None

            async def start(self, redis_url: str) -> None:
                """Имитирует старт шины."""
                self.started_with = redis_url

        bus = _FakeBus()
        fake_settings = SimpleNamespace(
            redis=SimpleNamespace(
                redis_url=REDIS_REAL_URL, redis_url_masked=REDIS_MASKED_URL
            )
        )

        monkeypatch.setattr(startup, "_logger", _FakeLogger())
        monkeypatch.setattr("src.backend.core.config.settings.settings", fake_settings)
        monkeypatch.setattr(
            "src.backend.core.config.features.feature_flags",
            SimpleNamespace(eventbus_facade=True, eventbus_dsl_enabled=False),
        )
        monkeypatch.setattr(
            "src.backend.core.messaging.event_bus.get_event_bus", lambda: bus
        )

        app = SimpleNamespace(state=SimpleNamespace())
        await startup._start_event_bus(app)

        assert bus.started_with == REDIS_REAL_URL, "подключение должно идти с паролем"
        assert records, "startup ничего не залогировал"
        assert all(REDIS_SECRET not in record for record in records), records
        assert any(REDIS_MASKED_URL in record for record in records), records
