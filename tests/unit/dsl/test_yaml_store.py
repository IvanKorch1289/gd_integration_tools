"""Unit tests for YAMLStore."""

# ruff: noqa: S101, SLF001

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.yaml_store import YAMLStore, _filename_to_route, _route_to_filename


def test_route_to_filename() -> None:
    assert _route_to_filename("orders.create") == "orders.create.yaml"
    assert _route_to_filename("a/b") == "a__b.yaml"
    assert _route_to_filename("a:b") == "a__b.yaml"


def test_filename_to_route() -> None:
    assert _filename_to_route("orders.create.yaml") == "orders.create"
    assert _filename_to_route("a__b.yaml") == "a.b"


class TestYAMLStore:
    @pytest.fixture
    def tmp_store(self, tmp_path: Path) -> YAMLStore:
        return YAMLStore(tmp_path)

    def test_init_creates_dir(self, tmp_path: Path) -> None:
        store = YAMLStore(tmp_path / "sub")
        assert (tmp_path / "sub").exists()

    def test_save(self, tmp_store: YAMLStore, tmp_path: Path) -> None:
        pipeline = MagicMock()
        pipeline.route_id = "orders.create"
        pipeline.to_yaml.return_value = "yaml: content\n"
        path = tmp_store.save(pipeline)
        assert path.exists()
        assert path.read_text() == "yaml: content\n"

    def test_load_missing(self, tmp_store: YAMLStore) -> None:
        with pytest.raises(FileNotFoundError):
            tmp_store.load("missing")

    def test_load_existing(self, tmp_store: YAMLStore) -> None:
        pipeline = MagicMock()
        pipeline.route_id = "orders.create"
        pipeline.to_yaml.return_value = "yaml: content\n"
        tmp_store.save(pipeline)

        with patch("src.backend.dsl.yaml_loader.load_pipeline_from_yaml") as mock_load:
            mock_pipeline = MagicMock()
            mock_load.return_value = mock_pipeline
            result = tmp_store.load("orders.create")
            assert result is mock_pipeline
            mock_load.assert_called_once_with("yaml: content\n")

    def test_delete_existing(self, tmp_store: YAMLStore) -> None:
        pipeline = MagicMock()
        pipeline.route_id = "orders.create"
        pipeline.to_yaml.return_value = ""
        tmp_store.save(pipeline)
        assert tmp_store.delete("orders.create") is True
        assert not tmp_store.exists("orders.create")

    def test_delete_missing(self, tmp_store: YAMLStore) -> None:
        assert tmp_store.delete("missing") is False

    def test_exists(self, tmp_store: YAMLStore) -> None:
        assert tmp_store.exists("missing") is False
        pipeline = MagicMock()
        pipeline.route_id = "orders.create"
        pipeline.to_yaml.return_value = ""
        tmp_store.save(pipeline)
        assert tmp_store.exists("orders.create") is True

    def test_list(self, tmp_store: YAMLStore) -> None:
        pipeline = MagicMock()
        pipeline.route_id = "orders.create"
        pipeline.to_yaml.return_value = ""
        tmp_store.save(pipeline)
        assert tmp_store.list() == ["orders.create"]

    def test_diff(self, tmp_store: YAMLStore) -> None:
        a = MagicMock()
        a.route_id = "a"
        a.to_yaml.return_value = "foo\n"
        b = MagicMock()
        b.route_id = "b"
        b.to_yaml.return_value = "bar\n"
        diff = tmp_store.diff(a, b)
        assert "--- a.yaml" in diff
        assert "+++ b.yaml" in diff

    def test_load_all(self, tmp_store: YAMLStore) -> None:
        pipeline = MagicMock()
        pipeline.route_id = "orders.create"
        pipeline.to_yaml.return_value = ""
        tmp_store.save(pipeline)

        with patch("src.backend.dsl.yaml_loader.load_pipeline_from_file") as mock_load:
            mock_load.return_value = pipeline
            result = tmp_store.load_all()
            assert len(result) == 1
            mock_load.assert_called_once()

    def test_load_all_skips_errors(self, tmp_store: YAMLStore, tmp_path: Path) -> None:
        (tmp_path / "bad.yaml").write_text("bad")
        with patch(
            "src.backend.dsl.yaml_loader.load_pipeline_from_file",
            side_effect=ValueError("bad yaml"),
        ):
            result = tmp_store.load_all()
            assert result == []
