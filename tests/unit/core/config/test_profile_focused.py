"""Focused tests for ``core.config.profile`` (Sprint 24 coverage ratchet).

Цель: покрытие 100% для маленького, но важного ``src/backend/core/config/profile.py``
(профиль запуска приложения).

Контракт API:
- ``APP_PROFILE_ENV = 'APP_PROFILE'`` — env-var name.
- ``AppProfileChoices(StrEnum)`` — 4 профиля: dev_light/dev/staging/prod.
- ``DEFAULT_PROFILE = AppProfileChoices.dev``.
- ``get_active_profile()`` — читает env, default при unset/invalid.
"""

from __future__ import annotations

import os

import pytest

from src.backend.core.config.profile import (
    APP_PROFILE_ENV,
    DEFAULT_PROFILE,
    AppProfileChoices,
    get_active_profile,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сбрасывает APP_PROFILE перед каждым тестом."""
    monkeypatch.delenv(APP_PROFILE_ENV, raising=False)


class TestConstants:
    """Module-level constants."""

    def test_app_profile_env_constant(self) -> None:
        """``APP_PROFILE_ENV == 'APP_PROFILE'``."""
        assert APP_PROFILE_ENV == "APP_PROFILE"

    def test_default_profile_is_dev(self) -> None:
        """``DEFAULT_PROFILE`` — ``AppProfileChoices.dev``."""
        assert DEFAULT_PROFILE == AppProfileChoices.dev


class TestAppProfileChoices:
    """``AppProfileChoices`` — StrEnum."""

    def test_dev_light_value(self) -> None:
        """``dev_light`` — 'dev_light'."""
        assert AppProfileChoices.dev_light == "dev_light"
        assert AppProfileChoices.dev_light.value == "dev_light"

    def test_dev_value(self) -> None:
        """``dev`` — 'dev'."""
        assert AppProfileChoices.dev == "dev"
        assert AppProfileChoices.dev.value == "dev"

    def test_staging_value(self) -> None:
        """``staging`` — 'staging'."""
        assert AppProfileChoices.staging == "staging"
        assert AppProfileChoices.staging.value == "staging"

    def test_prod_value(self) -> None:
        """``prod`` — 'prod'."""
        assert AppProfileChoices.prod == "prod"
        assert AppProfileChoices.prod.value == "prod"

    def test_all_four_profiles(self) -> None:
        """Всего 4 профиля."""
        assert len(AppProfileChoices) == 4

    def test_inherits_str(self) -> None:
        """``AppProfileChoices`` — подкласс ``str`` (StrEnum)."""
        assert issubclass(AppProfileChoices, str)

    def test_str_enum_iteration(self) -> None:
        """Итерация по enum возвращает все choices."""
        profiles = list(AppProfileChoices)
        assert set(profiles) == {
            AppProfileChoices.dev_light,
            AppProfileChoices.dev,
            AppProfileChoices.staging,
            AppProfileChoices.prod,
        }


class TestGetActiveProfile:
    """``get_active_profile()`` — читает env, fallback to default."""

    def test_no_env_returns_default(self) -> None:
        """``APP_PROFILE`` unset → ``DEFAULT_PROFILE``."""
        assert get_active_profile() == DEFAULT_PROFILE

    def test_empty_env_returns_default(self) -> None:
        """``APP_PROFILE=''`` → ``DEFAULT_PROFILE``."""
        os.environ[APP_PROFILE_ENV] = ""
        assert get_active_profile() == DEFAULT_PROFILE

    def test_whitespace_env_returns_default(self) -> None:
        """``APP_PROFILE='   '`` → ``DEFAULT_PROFILE``."""
        os.environ[APP_PROFILE_ENV] = "   "
        assert get_active_profile() == DEFAULT_PROFILE

    def test_dev_light(self) -> None:
        """``APP_PROFILE='dev_light'`` → ``dev_light``."""
        os.environ[APP_PROFILE_ENV] = "dev_light"
        assert get_active_profile() == AppProfileChoices.dev_light

    def test_dev(self) -> None:
        """``APP_PROFILE='dev'`` → ``dev``."""
        os.environ[APP_PROFILE_ENV] = "dev"
        assert get_active_profile() == AppProfileChoices.dev

    def test_staging(self) -> None:
        """``APP_PROFILE='staging'`` → ``staging``."""
        os.environ[APP_PROFILE_ENV] = "staging"
        assert get_active_profile() == AppProfileChoices.staging

    def test_prod(self) -> None:
        """``APP_PROFILE='prod'`` → ``prod``."""
        os.environ[APP_PROFILE_ENV] = "prod"
        assert get_active_profile() == AppProfileChoices.prod

    def test_uppercase_normalized(self) -> None:
        """``APP_PROFILE='PROD'`` (uppercase) → ``prod`` (lowercase)."""
        os.environ[APP_PROFILE_ENV] = "PROD"
        assert get_active_profile() == AppProfileChoices.prod

    def test_mixed_case_normalized(self) -> None:
        """``APP_PROFILE='Dev_Light'`` → ``dev_light``."""
        os.environ[APP_PROFILE_ENV] = "Dev_Light"
        assert get_active_profile() == AppProfileChoices.dev_light

    def test_with_whitespace_stripped(self) -> None:
        """``APP_PROFILE='  dev  '`` → ``dev`` (stripped)."""
        os.environ[APP_PROFILE_ENV] = "  dev  "
        assert get_active_profile() == AppProfileChoices.dev

    def test_invalid_value_returns_default(self) -> None:
        """``APP_PROFILE='unknown'`` → ``DEFAULT_PROFILE`` (ValueError caught)."""
        os.environ[APP_PROFILE_ENV] = "unknown_profile"
        assert get_active_profile() == DEFAULT_PROFILE

    def test_partial_invalid_value_returns_default(self) -> None:
        """``APP_PROFILE='devx'`` → ``DEFAULT_PROFILE`` (close but not match)."""
        os.environ[APP_PROFILE_ENV] = "devx"
        assert get_active_profile() == DEFAULT_PROFILE

    def test_empty_after_strip_returns_default(self) -> None:
        """``APP_PROFILE='   '`` (whitespace only) → ``DEFAULT_PROFILE``."""
        os.environ[APP_PROFILE_ENV] = "   "
        assert get_active_profile() == DEFAULT_PROFILE


class TestModuleExports:
    """``__all__`` exports."""

    def test_all_count(self) -> None:
        """``__all__`` содержит 4 symbols."""
        from src.backend.core.config import profile

        assert len(profile.__all__) == 4

    def test_all_present(self) -> None:
        """Все exports доступны."""
        from src.backend.core.config import profile

        for name in profile.__all__:
            obj = getattr(profile, name)
            assert obj is not None

    def test_all_names(self) -> None:
        """Конкретные имена."""
        from src.backend.core.config import profile

        assert "APP_PROFILE_ENV" in profile.__all__
        assert "DEFAULT_PROFILE" in profile.__all__
        assert "AppProfileChoices" in profile.__all__
        assert "get_active_profile" in profile.__all__
