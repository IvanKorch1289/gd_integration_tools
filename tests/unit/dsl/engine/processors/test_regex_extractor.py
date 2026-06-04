"""Unit tests for RegexExtractorProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.regex_extractor import RegexExtractorProcessor


def _ex(body: Any = None, properties: dict[str, Any] | None = None) -> Exchange[Any]:
    ex = Exchange(in_message=Message(body=body, headers={}))
    if properties:
        ex.properties.update(properties)
    return ex


class TestRegexExtractorProcessor:
    def test_init_empty_pattern_raises(self) -> None:
        with pytest.raises(ValueError, match="pattern must be non-empty"):
            RegexExtractorProcessor("")

    def test_init_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="mode must be one of"):
            RegexExtractorProcessor(".*", mode="bad")

    def test_init_invalid_pattern_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid pattern"):
            RegexExtractorProcessor("(")

    def test_resolve_source_body_str(self) -> None:
        proc = RegexExtractorProcessor(".*")
        assert proc._resolve_source(_ex("hello")) == "hello"

    def test_resolve_source_body_dict(self) -> None:
        proc = RegexExtractorProcessor(".*", source="body.name")
        assert proc._resolve_source(_ex({"name": "Alice"})) == "Alice"

    def test_resolve_source_properties(self) -> None:
        proc = RegexExtractorProcessor(".*", source="properties.key")
        assert proc._resolve_source(_ex({}, {"key": "val"})) == "val"

    def test_apply_target_body(self) -> None:
        proc = RegexExtractorProcessor(".*", to="body.result")
        ex = _ex({})
        proc._apply_target(ex, ["match"])
        assert ex.in_message.body == {"result": ["match"]}

    def test_apply_target_properties(self) -> None:
        proc = RegexExtractorProcessor(".*", to="properties.res")
        ex = _ex({})
        proc._apply_target(ex, ["match"])
        assert ex.properties["res"] == ["match"]

    @pytest.mark.asyncio
    async def test_process_all_mode(self) -> None:
        with (
            patch.object(
                RegexExtractorProcessor, "_resolve_source", return_value="a1 b2 a3"
            ),
            patch(
                "src.backend.core.config.features.feature_flags.proc_regex_extractor",
                True,
            ),
        ):
            proc = RegexExtractorProcessor(r"a\d+", mode="all")
            ex = _ex({})
            await proc.process(ex, None)  # type: ignore[arg-type]
            assert ex.in_message.body == {"regex_result": ["a1", "a3"]}

    @pytest.mark.asyncio
    async def test_process_first_mode(self) -> None:
        with (
            patch.object(
                RegexExtractorProcessor, "_resolve_source", return_value="a1 b2"
            ),
            patch(
                "src.backend.core.config.features.feature_flags.proc_regex_extractor",
                True,
            ),
        ):
            proc = RegexExtractorProcessor(r"a\d+", mode="first")
            ex = _ex({})
            await proc.process(ex, None)  # type: ignore[arg-type]
            assert ex.in_message.body == {"regex_result": "a1"}

    @pytest.mark.asyncio
    async def test_process_first_named_mode(self) -> None:
        with (
            patch.object(
                RegexExtractorProcessor, "_resolve_source", return_value="order_123"
            ),
            patch(
                "src.backend.core.config.features.feature_flags.proc_regex_extractor",
                True,
            ),
        ):
            proc = RegexExtractorProcessor(r"order_(?P<id>\d+)", mode="first_named")
            ex = _ex({})
            await proc.process(ex, None)  # type: ignore[arg-type]
            assert ex.in_message.body == {"regex_result": {"id": "123"}}

    @pytest.mark.asyncio
    async def test_process_groups_mode(self) -> None:
        with (
            patch.object(
                RegexExtractorProcessor, "_resolve_source", return_value="order_123"
            ),
            patch(
                "src.backend.core.config.features.feature_flags.proc_regex_extractor",
                True,
            ),
        ):
            proc = RegexExtractorProcessor(r"order_(\d+)", mode="groups")
            ex = _ex({})
            await proc.process(ex, None)  # type: ignore[arg-type]
            assert ex.in_message.body == {"regex_result": ("123",)}

    @pytest.mark.asyncio
    async def test_process_feature_flag_off(self) -> None:
        with patch(
            "src.backend.core.config.features.feature_flags.proc_regex_extractor", False
        ):
            proc = RegexExtractorProcessor(r".*")
            ex = _ex({})
            await proc.process(ex, None)  # type: ignore[arg-type]
            assert ex.properties.get("regex_extractor_status") == "skipped"

    def test_to_spec_defaults(self) -> None:
        proc = RegexExtractorProcessor(r"hello")
        assert proc.to_spec() == {"regex_extractor": {"pattern": "hello"}}

    def test_to_spec_full(self) -> None:
        proc = RegexExtractorProcessor(
            r"hello", source="body.x", to="body.y", mode="first", flags=2
        )
        spec = proc.to_spec()
        assert spec["regex_extractor"] == {
            "pattern": "hello",
            "source": "body.x",
            "to": "body.y",
            "mode": "first",
            "flags": 2,
        }
