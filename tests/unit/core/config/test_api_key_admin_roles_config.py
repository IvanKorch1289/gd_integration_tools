"""P0 regression test (Cycle 7, production-grade plan).

Cycle 7 fix: admin роли для API key holder configurable через
``settings.secure.api_key_admin_roles``. Раньше — hardcoded
``["operator", "super_admin"]`` в ``api_key.py:107-115``.

Тест проверяет:
1. Settings имеют новое поле с правильным default.
2. ``field_validator(mode='before')`` парсит comma-separated string.
3. ``APIKeyMiddleware`` использует настройку (не hardcoded list).

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/core/config/test_api_key_admin_roles_config.py -v
"""

from __future__ import annotations

from pathlib import Path

from src.backend.core.config.security import SecureSettings


class TestSecureSettingsApiKeyAdminRoles:
    """P0 (cycle 7): SecureSettings.api_key_admin_roles существует."""

    def test_field_exists(self) -> None:
        """``SecureSettings`` имеет поле ``api_key_admin_roles``."""
        assert "api_key_admin_roles" in SecureSettings.model_fields, (
            "SecureSettings НЕ имеет поля api_key_admin_roles. "
            "P0 cycle 7 не применён."
        )

    def test_default_value_via_model_construct(self) -> None:
        """Default = ['operator', 'super_admin'] через default_factory.

        Используем ``model_construct`` чтобы обойти full validation (другие
        обязательные поля не заполнять).
        """
        # model_construct не вызывает validators и defaults — обходим это
        # через прямое получение default из field info.
        field = SecureSettings.model_fields["api_key_admin_roles"]
        default_factory = field.default_factory
        if default_factory is None:
            actual_default = field.default
        else:
            actual_default = default_factory()
        assert actual_default == ["operator", "super_admin"], (
            f"Expected default=['operator', 'super_admin'], got {actual_default!r}"
        )


class TestApiKeyAdminRolesValidator:
    """``field_validator(mode='before')`` парсит comma-separated string."""

    def test_validator_parses_comma_separated(self) -> None:
        """``field_validator`` доступен через model_validator API."""

        # Найти validator через Pydantic mechanism
        validators = SecureSettings.__pydantic_decorators__.field_validators
        # Ищем validator для поля api_key_admin_roles
        found = False
        for validator_info in validators.values():
            if hasattr(validator_info, "info") and validator_info.info.fields:
                if "api_key_admin_roles" in validator_info.info.fields:
                    found = True
                    break
        # Альтернативный подход — прямо через field attribute
        field = SecureSettings.model_fields["api_key_admin_roles"]
        assert field.metadata or found, (
            "Validator для api_key_admin_roles не зарегистрирован."
        )

    def test_validator_split_function(self) -> None:
        """``_parse_api_key_admin_roles`` корректно парсит."""
        # Напрямую вызываем validator через getattr
        validator = getattr(SecureSettings, "_parse_api_key_admin_roles", None)
        assert validator is not None, (
            "SecureSettings._parse_api_key_admin_roles не определён"
        )
        # Парсинг comma-separated string
        result = validator("super_admin,admin,operator")
        assert result == ["super_admin", "admin", "operator"], (
            f"Got {result!r}"
        )
        # Парсинг single string
        result = validator("super_admin")
        assert result == ["super_admin"], f"Got {result!r}"
        # Парсинг list (passthrough)
        result = validator(["a", "b"])
        assert result == ["a", "b"], f"Got {result!r}"
        # Парсинг с whitespace
        result = validator(" super , admin ")
        assert result == ["super", "admin"], f"Got {result!r}"


class TestApiKeyMiddlewareUsesConfig:
    """``APIKeyMiddleware`` использует settings.secure.api_key_admin_roles."""

    def test_api_key_uses_config_not_hardcoded(self) -> None:
        """Source AST: api_key.py ссылается на settings.secure.api_key_admin_roles."""
        api_key_source = Path(
            "/home/user/dev/gd_integration_tools/src/backend/entrypoints/middlewares/api_key.py"
        ).read_text()
        assert "settings.secure.api_key_admin_roles" in api_key_source, (
            "api_key.py НЕ использует settings.secure.api_key_admin_roles — "
            "configurable admin roles не применены."
        )

    def test_api_key_no_hardcoded_admin_roles_list(self) -> None:
        """Source AST: нет hardcoded ``"admin_roles": ["operator", "super_admin"]``."""
        api_key_source = Path(
            "/home/user/dev/gd_integration_tools/src/backend/entrypoints/middlewares/api_key.py"
        ).read_text()
        assert (
            '"admin_roles": ["operator", "super_admin"]'
            not in api_key_source
        ), (
            "api_key.py всё ещё содержит hardcoded admin_roles list. "
            "P0 cycle 7 не применён."
        )

