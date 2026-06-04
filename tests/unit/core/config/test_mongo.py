"""Tests for src.backend.core.config.mongo."""

from __future__ import annotations

import pytest

from src.backend.core.config.mongo import MongoConnectionSettings


class TestMongoConnectionSettings:
    def test_defaults(self) -> None:
        s = MongoConnectionSettings(
            username="u",
            password="password123",
            name="db",
            host="h",
            port=27017,
            min_pool_size=1,
            max_pool_size=10,
            timeout=5000,
        )
        assert s.enabled is True
        assert s.host == "h"
        assert s.port == 27017

    def test_connection_string(self) -> None:
        s = MongoConnectionSettings(
            username="u",
            password="password123",
            name="db",
            host="h",
            port=27017,
            min_pool_size=1,
            max_pool_size=10,
            timeout=5000,
        )
        assert (
            s.connection_string == "mongodb://u:password123@h:27017/db?authSource=admin"
        )

    def test_password_min_length(self) -> None:
        with pytest.raises(Exception):
            MongoConnectionSettings(
                username="u",
                password="short",
                name="db",
                host="h",
                port=27017,
                min_pool_size=1,
                max_pool_size=10,
                timeout=5000,
            )
