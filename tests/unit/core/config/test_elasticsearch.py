"""Tests for src.backend.core.config.elasticsearch."""

from __future__ import annotations

from src.backend.core.config.elasticsearch import ElasticsearchSettings


class TestElasticsearchSettings:
    def test_defaults(self) -> None:
        s = ElasticsearchSettings()
        assert s.hosts == ["http://localhost:9200"]
        assert s.verify_certs is True
        assert s.enabled is False
        assert s.index_prefix == "gd_"

    def test_custom_values(self) -> None:
        s = ElasticsearchSettings(
            hosts=["http://es:9200"], enabled=True, api_key="key", index_prefix="test_"
        )
        assert s.hosts == ["http://es:9200"]
        assert s.enabled is True
        assert s.api_key == "key"
        assert s.index_prefix == "test_"
