"""Unit tests for src.backend.core.di.providers.db (T-P1.2c split)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.backend.core.di.providers import db


class TestClickHouseClient:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_clickhouse")
        db.set_clickhouse_client_provider(mock)
        assert db.get_clickhouse_client_provider() is mock


class TestMongoClient:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_mongo")
        db.set_mongo_client_provider(mock)
        assert db.get_mongo_client_provider() is mock


class TestFileRepo:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_filerepo")
        db.set_file_repo_provider(mock)
        assert db.get_file_repo_provider() is mock


class TestConnectorConfigStore:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_cfgstore")
        db.set_connector_config_store_provider(mock)
        assert db.get_connector_config_store_provider() is mock


class TestConnectorRegistry:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_registry")
        db.set_connector_registry_provider(mock)
        assert db.get_connector_registry_provider() is mock

    def test_errors_provider_set(self) -> None:
        # get-only function (no set_), just verify import
        from src.backend.core.di.providers.db import get_connector_registry_errors_provider
        assert callable(get_connector_registry_errors_provider)


class TestCdcClient:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_cdc")
        db.set_cdc_client_provider(mock)
        assert db.get_cdc_client_provider() is mock


class TestS3Service:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_s3")
        db.set_s3_service_provider(mock)
        assert db.get_s3_service_provider() is mock


class TestDbModuleIsolation:
    """Each domain has independent _overrides."""

    def test_overrides_isolated_from_cache(self) -> None:
        # Set db override
        db.set_clickhouse_client_provider("DB_VALUE")
        # Set cache override (different domain)
        from src.backend.core.di.providers import cache
        cache.set_cache_invalidator_provider("CACHE_VALUE")
        # Each isolated
        assert db.get_clickhouse_client_provider() == "DB_VALUE"
        assert cache.get_cache_invalidator_provider() == "CACHE_VALUE"
