"""Unit tests for external database read-replica support (S38.1)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.external_databases.connection import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.infrastructure.database.database import (
    DatabaseBundle,
    DatabaseInitializer,
    ExternalDatabaseRegistry,
)


class TestExternalDatabaseReplicaSettings:
    def test_replica_dsn_field_exists(self) -> None:
        cfg = ExternalDatabaseConnectionSettings(
            name="pg_1",
            profile_name="pg_1",
            type="postgresql",
            host="localhost",
            port=5432,
            db_name="test",
            async_driver="asyncpg",
            sync_driver="psycopg2",
            db_schema="public",
            echo=False,
            username="user",
            password="secret",
            pool_size=5,
            max_overflow=5,
            pool_recycle=1800,
            pool_timeout=30,
            pool_pre_ping=True,
            connect_timeout=10,
            command_timeout=30,
            ssl_mode=None,
            ca_bundle=None,
            max_retries=0,
            circuit_breaker_max_failures=5,
            circuit_breaker_reset_timeout=30,
            slow_query_threshold=1.0,
            replica_dsn="postgresql+asyncpg://user:pwd@replica:5432/test",
        )
        assert cfg.replica_dsn == "postgresql+asyncpg://user:pwd@replica:5432/test"
        assert cfg.replica_async_connection_url == cfg.replica_dsn

    def test_replica_dsn_optional(self) -> None:
        cfg = ExternalDatabaseConnectionSettings(
            name="pg_1",
            profile_name="pg_1",
            type="postgresql",
            host="localhost",
            port=5432,
            db_name="test",
            async_driver="asyncpg",
            sync_driver="psycopg2",
            db_schema="public",
            echo=False,
            username="user",
            password="secret",
            pool_size=5,
            max_overflow=5,
            pool_recycle=1800,
            pool_timeout=30,
            pool_pre_ping=True,
            connect_timeout=10,
            command_timeout=30,
            ssl_mode=None,
            ca_bundle=None,
            max_retries=0,
            circuit_breaker_max_failures=5,
            circuit_breaker_reset_timeout=30,
            slow_query_threshold=1.0,
        )
        assert cfg.replica_dsn is None
        assert cfg.replica_async_connection_url is None


class TestExternalDatabaseRegistryReplica:
    def test_get_smart_session_manager_with_replica(self) -> None:
        cfg = ExternalDatabaseConnectionSettings(
            name="pg_1",
            profile_name="pg_1",
            type="postgresql",
            host="localhost",
            port=5432,
            db_name="test",
            async_driver="asyncpg",
            sync_driver="psycopg2",
            db_schema="public",
            echo=False,
            username="user",
            password="secret",
            pool_size=1,
            max_overflow=1,
            pool_recycle=1800,
            pool_timeout=30,
            pool_pre_ping=True,
            connect_timeout=10,
            command_timeout=30,
            ssl_mode=None,
            ca_bundle=None,
            max_retries=0,
            circuit_breaker_max_failures=5,
            circuit_breaker_reset_timeout=30,
            slow_query_threshold=1.0,
            replica_dsn="postgresql+asyncpg://user:pwd@replica:5432/test",
        )
        registry = ExternalDatabaseRegistry(configs={"pg_1": cfg})
        bundle = registry.get_bundle("pg_1")
        assert bundle.replica_engine is not None
        assert bundle.replica_session_maker is not None

    def test_get_smart_session_manager_without_replica(self) -> None:
        cfg = ExternalDatabaseConnectionSettings(
            name="pg_1",
            profile_name="pg_1",
            type="postgresql",
            host="localhost",
            port=5432,
            db_name="test",
            async_driver="asyncpg",
            sync_driver="psycopg2",
            db_schema="public",
            echo=False,
            username="user",
            password="secret",
            pool_size=1,
            max_overflow=1,
            pool_recycle=1800,
            pool_timeout=30,
            pool_pre_ping=True,
            connect_timeout=10,
            command_timeout=30,
            ssl_mode=None,
            ca_bundle=None,
            max_retries=0,
            circuit_breaker_max_failures=5,
            circuit_breaker_reset_timeout=30,
            slow_query_threshold=1.0,
        )
        registry = ExternalDatabaseRegistry(configs={"pg_1": cfg})
        bundle = registry.get_bundle("pg_1")
        assert bundle.replica_engine is None
        assert bundle.replica_session_maker is None


class TestDatabaseBundleReplica:
    def test_bundle_has_replica_fields(self) -> None:
        bundle = DatabaseBundle(
            name="test",
            settings=MagicMock(),
            async_engine=MagicMock(),
            async_session_maker=MagicMock(),
            sync_engine=None,
            sync_session_maker=None,
            replica_engine=MagicMock(),
            replica_session_maker=MagicMock(),
        )
        assert bundle.replica_engine is not None
        assert bundle.replica_session_maker is not None
