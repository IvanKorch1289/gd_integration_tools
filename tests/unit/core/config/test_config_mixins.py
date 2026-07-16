"""Unit-тесты для Settings Mixins.

Тестирует новые миксины: APIConnectionMixin, DBPoolMixin, ResilienceMixin.
"""

import pytest
from pydantic import BaseModel

from src.backend.core.config.mixins import (
    APIConnectionMixin,
    ConnectionMixin,
    DBPoolMixin,
    LLMModelMixin,
    ResilienceMixin,
    RetryMixin,
)


class TestAPIConnectionMixin:
    """Тесты APIConnectionMixin."""

    def test_default_values(self):
        """Проверяет значения по умолчанию."""

        class TestSettings(APIConnectionMixin, BaseModel):
            pass

        s = TestSettings()
        assert s.base_url == ""
        assert s.timeout_s == 30.0
        assert s.max_retries == 3
        assert s.retry_backoff_factor == 1.0

    def test_custom_values(self):
        """Проверяет установку кастомных значений."""

        class TestSettings(APIConnectionMixin, BaseModel):
            pass

        s = TestSettings(
            base_url="https://api.example.com",
            timeout_s=60.0,
            max_retries=5,
            retry_backoff_factor=2.0,
        )
        assert s.base_url == "https://api.example.com"
        assert s.timeout_s == 60.0
        assert s.max_retries == 5
        assert s.retry_backoff_factor == 2.0

    def test_validation_timeout_s_positive(self):
        """timeout_s должен быть положительным."""

        class TestSettings(APIConnectionMixin, BaseModel):
            pass

        with pytest.raises(Exception):  # pydantic ValidationError
            TestSettings(timeout_s=0)

    def test_validation_max_retries_non_negative(self):
        """max_retries должен быть >= 0."""

        class TestSettings(APIConnectionMixin, BaseModel):
            pass

        s = TestSettings(max_retries=0)
        assert s.max_retries == 0


class TestDBPoolMixin:
    """Тесты DBPoolMixin."""

    def test_default_values(self):
        """Проверяет значения по умолчанию."""

        class TestSettings(DBPoolMixin, BaseModel):
            pass

        s = TestSettings()
        assert s.pool_size == 10
        assert s.pool_timeout_s == 30.0
        assert s.max_overflow == 10

    def test_custom_values(self):
        """Проверяет установку кастомных значений."""

        class TestSettings(DBPoolMixin, BaseModel):
            pass

        s = TestSettings(
            pool_size=50,
            pool_timeout_s=60.0,
            max_overflow=20,
        )
        assert s.pool_size == 50
        assert s.pool_timeout_s == 60.0
        assert s.max_overflow == 20

    def test_validation_pool_size_positive(self):
        """pool_size должен быть >= 1."""

        class TestSettings(DBPoolMixin, BaseModel):
            pass

        with pytest.raises(Exception):  # pydantic ValidationError
            TestSettings(pool_size=0)


class TestResilienceMixin:
    """Тесты ResilienceMixin."""

    def test_default_values(self):
        """Проверяет значения по умолчанию."""

        class TestSettings(ResilienceMixin, BaseModel):
            pass

        s = TestSettings()
        assert s.circuit_breaker_max_failures == 5
        assert s.circuit_breaker_reset_timeout == 60.0

    def test_custom_values(self):
        """Проверяет установку кастомных значений."""

        class TestSettings(ResilienceMixin, BaseModel):
            pass

        s = TestSettings(
            circuit_breaker_max_failures=10,
            circuit_breaker_reset_timeout=120.0,
        )
        assert s.circuit_breaker_max_failures == 10
        assert s.circuit_breaker_reset_timeout == 120.0

    def test_zero_failures_allowed(self):
        """circuit_breaker_max_failures может быть 0 (отключен)."""

        class TestSettings(ResilienceMixin, BaseModel):
            pass

        s = TestSettings(circuit_breaker_max_failures=0)
        assert s.circuit_breaker_max_failures == 0


class TestMixinComposition:
    """Тесты композиции миксинов."""

    def test_api_connection_with_resilience(self):
        """APIConnectionMixin + ResilienceMixin."""

        class ApiServiceSettings(APIConnectionMixin, ResilienceMixin, BaseModel):
            service_name: str = "test"

        s = ApiServiceSettings(
            base_url="https://api.test.com",
            timeout_s=45.0,
            circuit_breaker_max_failures=10,
        )
        assert s.service_name == "test"
        assert s.base_url == "https://api.test.com"
        assert s.timeout_s == 45.0
        assert s.circuit_breaker_max_failures == 10

    def test_db_pool_with_resilience(self):
        """DBPoolMixin + ResilienceMixin."""

        class DbSettings(DBPoolMixin, ResilienceMixin, BaseModel):
            db_name: str = "testdb"

        s = DbSettings(
            pool_size=30,
            pool_timeout_s=45.0,
            circuit_breaker_max_failures=7,
        )
        assert s.db_name == "testdb"
        assert s.pool_size == 30
        assert s.circuit_breaker_max_failures == 7

    def test_all_mixins_together(self):
        """Все 4 базовых миксина вместе."""

        class FullSettings(
            ConnectionMixin, RetryMixin, LLMModelMixin, APIConnectionMixin, BaseModel
        ):
            pass

        s = FullSettings()
        # ConnectionMixin
        assert s.host == ""
        assert s.port == 0
        assert s.base_url == ""
        # RetryMixin
        assert s.max_retries == 3
        # LLMModelMixin
        assert s.model == "gpt-4o-mini"
        assert s.max_tokens == 4096
        # APIConnectionMixin
        assert s.timeout_s == 30.0

    def test_antivirus_like_settings(self):
        """Настройки, похожие на AntivirusAPISettings."""

        class AntivirusLikeSettings(APIConnectionMixin, ResilienceMixin, BaseModel):
            endpoints: dict[str, str] = {"scan": "/scan"}
            raise_for_status: bool = True

        s = AntivirusLikeSettings(
            base_url="https://av.example.com",
            timeout_s=130.0,
            max_retries=2,
            circuit_breaker_max_failures=5,
        )
        assert s.base_url == "https://av.example.com"
        assert s.timeout_s == 130.0
        assert s.max_retries == 2
        assert s.endpoints == {"scan": "/scan"}
        assert s.raise_for_status is True
