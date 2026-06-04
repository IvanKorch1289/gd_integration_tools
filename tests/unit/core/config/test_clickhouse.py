"""Tests for src.backend.core.config.clickhouse."""

from __future__ import annotations

import pytest

from src.backend.core.config.clickhouse import ClickHouseSettings


class TestClickHouseSettings:
    def test_defaults(self) -> None:
        s = ClickHouseSettings()
        assert s.host == "localhost"
        assert s.port == 9000
        assert s.http_port == 8123
        assert s.enabled is False
        assert s.pool_size == 20

    def test_custom_values(self) -> None:
        s = ClickHouseSettings(host="ch", port=8123, enabled=True, pool_size=10)
        assert s.host == "ch"
        assert s.port == 8123
        assert s.enabled is True
        assert s.pool_size == 10

    def test_bounds(self) -> None:
        with pytest.raises(Exception):
            ClickHouseSettings(port=0)
        with pytest.raises(Exception):
            ClickHouseSettings(pool_size=0)
