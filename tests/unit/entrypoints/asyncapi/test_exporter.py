"""Unit tests for AsyncAPI exporter (FastStream specification builder)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class TestCollectBrokers:
    def test_collects_all_brokers(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import _collect_brokers

        fake_client = MagicMock()
        fake_client.redis_router = MagicMock(broker="redis_broker")
        fake_client.rabbit_router = MagicMock(broker="rabbit_broker")
        fake_client.kafka_router = MagicMock(broker="kafka_broker")

        with patch(
            "src.backend.infrastructure.clients.messaging.stream.get_stream_client",
            return_value=fake_client,
        ):
            pairs = _collect_brokers()

        labels = [label for label, _ in pairs]
        assert "redis" in labels
        assert "rabbit" in labels
        assert "kafka" in labels

    def test_skips_missing_routers(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import _collect_brokers

        fake_client = MagicMock()
        fake_client.redis_router = MagicMock(broker="redis_broker")
        fake_client.rabbit_router = None
        fake_client.kafka_router = MagicMock(broker="kafka_broker")

        with patch(
            "src.backend.infrastructure.clients.messaging.stream.get_stream_client",
            return_value=fake_client,
        ):
            pairs = _collect_brokers()

        labels = [label for label, _ in pairs]
        assert "redis" in labels
        assert "rabbit" not in labels
        assert "kafka" in labels

    def test_skips_missing_broker_attr(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import _collect_brokers

        fake_client = MagicMock()
        fake_client.redis_router = MagicMock(broker=None)
        fake_client.rabbit_router = MagicMock(broker="rabbit_broker")
        fake_client.kafka_router = MagicMock(broker="kafka_broker")

        with patch(
            "src.backend.infrastructure.clients.messaging.stream.get_stream_client",
            return_value=fake_client,
        ):
            pairs = _collect_brokers()

        labels = [label for label, _ in pairs]
        assert "redis" not in labels
        assert "rabbit" in labels
        assert "kafka" in labels

    def test_returns_empty_on_exception(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import _collect_brokers

        with patch(
            "src.backend.infrastructure.clients.messaging.stream.get_stream_client",
            side_effect=RuntimeError("client down"),
        ):
            pairs = _collect_brokers()

        assert pairs == []


class TestEmptySpecDict:
    def test_structure(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import _empty_spec_dict

        spec = _empty_spec_dict("TestTitle", "1.2.3", "TestDesc")
        assert spec["asyncapi"] == "3.0.0"
        assert spec["info"]["title"] == "TestTitle"
        assert spec["info"]["version"] == "1.2.3"
        assert spec["info"]["description"] == "TestDesc"
        assert spec["channels"] == {}
        assert spec["operations"] == {}


class TestBuildAsyncapiSpec:
    def test_returns_spec_when_brokers_present(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import build_asyncapi_spec

        fake_broker = MagicMock()
        fake_spec = MagicMock()
        fake_spec.to_specification.return_value = fake_spec

        with (
            patch(
                "src.backend.entrypoints.asyncapi.exporter._collect_brokers",
                return_value=[("redis", fake_broker), ("rabbit", fake_broker)],
            ),
            patch(
                "faststream.specification.AsyncAPI", return_value=fake_spec
            ) as mock_asyncapi_cls,
        ):
            spec = build_asyncapi_spec("T", "V", "D")

        assert spec is fake_spec
        mock_asyncapi_cls.assert_called_once_with(
            fake_broker, title="T", version="V", description="D", schema_version="3.0.0"
        )
        assert fake_spec.add_broker.call_count == 1
        fake_spec.to_specification.assert_called_once()

    def test_returns_none_when_no_brokers(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import build_asyncapi_spec

        with patch(
            "src.backend.entrypoints.asyncapi.exporter._collect_brokers",
            return_value=[],
        ):
            spec = build_asyncapi_spec()

        assert spec is None


class TestBuildAsyncapiYaml:
    def test_uses_spec_to_yaml(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import build_asyncapi_yaml

        fake_spec = MagicMock()
        fake_spec.to_yaml.return_value = "yaml_content"

        with patch(
            "src.backend.entrypoints.asyncapi.exporter.build_asyncapi_spec",
            return_value=fake_spec,
        ):
            result = build_asyncapi_yaml()

        assert result == "yaml_content"
        fake_spec.to_yaml.assert_called_once()

    def test_fallback_empty_spec(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import build_asyncapi_yaml

        with (
            patch(
                "src.backend.entrypoints.asyncapi.exporter.build_asyncapi_spec",
                return_value=None,
            ),
            patch("yaml.safe_dump", return_value="fallback_yaml") as mock_dump,
        ):
            result = build_asyncapi_yaml()

        assert result == "fallback_yaml"
        mock_dump.assert_called_once()
        args = mock_dump.call_args[0][0]
        assert args["asyncapi"] == "3.0.0"


class TestBuildAsyncapiJson:
    def test_uses_spec_to_json(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import build_asyncapi_json

        fake_spec = MagicMock()
        fake_spec.to_json.return_value = "json_content"

        with patch(
            "src.backend.entrypoints.asyncapi.exporter.build_asyncapi_spec",
            return_value=fake_spec,
        ):
            result = build_asyncapi_json()

        assert result == "json_content"
        fake_spec.to_json.assert_called_once()

    def test_fallback_empty_spec(self) -> None:
        from src.backend.entrypoints.asyncapi.exporter import build_asyncapi_json

        with (
            patch(
                "src.backend.entrypoints.asyncapi.exporter.build_asyncapi_spec",
                return_value=None,
            ),
            patch("json.dumps", return_value="fallback_json") as mock_dumps,
        ):
            result = build_asyncapi_json()

        assert result == "fallback_json"
        mock_dumps.assert_called_once()
        args = mock_dumps.call_args[0][0]
        assert args["asyncapi"] == "3.0.0"
