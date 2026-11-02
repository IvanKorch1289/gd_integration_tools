"""Маскирование секретов интеграционных каналов (ADR-0378).

Дефект (smoke 2026-10-29): ``express.signature_secret`` и
``telegram.secret_key`` были plain-``str`` — значения утекали открытым
текстом в ``GET /api/v1/admin/config`` (в ответе было видно ``secret_key=...``
без маскирования).

Контракт фикса:

* поля-секреты типизированы как ``SecretStr``;
* в ``model_dump()``/``model_dump_json()`` значения маскируются (``***``);
* рантайм-значение остаётся доступным через ``secret_value()``;
* публичные строковые контракты (``TelegramBotSettings.token``,
  ``AuthConfig.express_jwt.secret_key``) не сломаны.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import SecretStr

from src.backend.core.config.express import ExpressSettings
from src.backend.core.config.secret import secret_value
from src.backend.core.config.telegram import TelegramBotSettings

pytestmark = pytest.mark.unit

#: Значение-маркер: не должно встречаться в дампах конфигурации.
SENTINEL = "s3cr3t-express-signature-42"

#: Поля-секреты интеграционных каналов (ADR-0378).
SECRET_FIELDS: tuple[tuple[type, str], ...] = (
    (ExpressSettings, "signature_secret"),
    (ExpressSettings, "secret_key"),
    (TelegramBotSettings, "signature_secret"),
    (TelegramBotSettings, "secret_key"),
)


def _model_with_secret(model_cls: type, field_name: str) -> Any:
    """Создаёт экземпляр модели с непустым секретом в ``field_name``."""
    return model_cls.model_construct(**{field_name: SecretStr(SENTINEL)})


class TestSecretFieldsAreTyped:
    """Поля-секреты типизированы как ``SecretStr``."""

    @pytest.mark.parametrize(
        ("model_cls", "field_name"),
        SECRET_FIELDS,
        ids=[f"{m.__name__}.{f}" for m, f in SECRET_FIELDS],
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
        SECRET_FIELDS,
        ids=[f"{m.__name__}.{f}" for m, f in SECRET_FIELDS],
    )
    def test_secret_not_leaked_in_repr(self, model_cls: type, field_name: str) -> None:
        """Значение секрета не попадает в ``repr`` модели."""
        instance = _model_with_secret(model_cls, field_name)
        assert SENTINEL not in repr(instance)

    @pytest.mark.parametrize(
        ("model_cls", "field_name"),
        SECRET_FIELDS,
        ids=[f"{m.__name__}.{f}" for m, f in SECRET_FIELDS],
    )
    def test_secret_masked_in_model_dump(
        self, model_cls: type, field_name: str
    ) -> None:
        """Значение секрета маскируется в дампе модели."""
        instance = _model_with_secret(model_cls, field_name)
        dumped = instance.model_dump()
        assert dumped[field_name] == "***"
        assert SENTINEL not in instance.model_dump_json()

    @pytest.mark.parametrize(
        ("model_cls", "field_name"),
        SECRET_FIELDS,
        ids=[f"{m.__name__}.{f}" for m, f in SECRET_FIELDS],
    )
    def test_runtime_value_still_available(
        self, model_cls: type, field_name: str
    ) -> None:
        """Рантайм-значение секрета доступно через ``secret_value``."""
        instance = _model_with_secret(model_cls, field_name)
        assert secret_value(getattr(instance, field_name)) == SENTINEL


class TestPublicContractsPreserved:
    """Публичные строковые контракты не сломаны."""

    def test_telegram_token_is_plain_string(self) -> None:
        """``TelegramBotSettings.token`` возвращает ``{bot_id}:{secret}``."""
        settings = TelegramBotSettings.model_construct(
            bot_id="12345", secret_key=SecretStr(SENTINEL)
        )
        assert settings.token == f"12345:{SENTINEL}"
        assert isinstance(settings.token, str)

    def test_empty_secret_keeps_token_empty(self) -> None:
        """Пустой секрет → пустой токен (как до типизации)."""
        settings = TelegramBotSettings.model_construct(
            bot_id="12345", secret_key=SecretStr("")
        )
        assert settings.token == ""

    def test_auth_config_returns_plain_string(self) -> None:
        """``build_auth_config`` отдаёт ``str`` (не ``SecretStr``)."""
        from src.backend.core.config.auth import build_auth_config

        express = ExpressSettings.model_construct(
            bot_id="bot-1", secret_key=SecretStr(SENTINEL), enabled=True
        )
        cfg = build_auth_config(express=express)
        assert cfg.express_jwt.secret_key == SENTINEL
        assert isinstance(cfg.express_jwt.secret_key, str)


class TestAdminConfigHasNoPlaintextSecrets:
    """В admin-config нет открытых секретов."""

    async def test_admin_config_masks_integration_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``AdminService.get_config()`` не отдаёт секреты открытым текстом."""
        from src.backend.core.config.settings import settings
        from src.backend.services.core.admin import AdminService

        for model in (settings.express, settings.telegram):
            monkeypatch.setattr(
                model, "signature_secret", SecretStr(SENTINEL), raising=False
            )
            monkeypatch.setattr(model, "secret_key", SecretStr(SENTINEL), raising=False)

        config = await AdminService().get_config()
        dumped = json.dumps(config, default=str)

        assert SENTINEL not in dumped
        assert config["express"]["signature_secret"] == "***"
        assert config["express"]["secret_key"] == "***"
        assert config["telegram"]["signature_secret"] == "***"
        assert config["telegram"]["secret_key"] == "***"
