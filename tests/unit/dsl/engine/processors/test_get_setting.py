"""Unit tests for GetSettingProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.get_setting import GetSettingProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestGetSettingProcessor:
    def test_init_empty_path_raises(self) -> None:
        with pytest.raises(ValueError, match="path must be non-empty"):
            GetSettingProcessor("")

    def test_resolve_path_dict(self) -> None:
        proc = GetSettingProcessor("a.b")
        root = {"a": {"b": 42}}
        val = proc._resolve_path(root, "a.b")
        assert val == 42

    def test_resolve_path_missing(self) -> None:
        proc = GetSettingProcessor("a.b")
        root = {"a": {}}
        val = proc._resolve_path(root, "a.b")
        from src.backend.dsl.engine.processors.get_setting import _MISSING

        assert val is _MISSING

    def test_resolve_path_object(self) -> None:
        proc = GetSettingProcessor("a.b")
        obj = MagicMock()
        obj.a = MagicMock()
        obj.a.b = 99
        val = proc._resolve_path(obj, "a.b")
        assert val == 99

    def test_apply_target_body(self) -> None:
        proc = GetSettingProcessor("x", to="body.y")
        exchange = _ex({})
        proc._apply_target(exchange, 123)
        assert exchange.in_message.body == {"y": 123}

    def test_apply_target_properties(self) -> None:
        proc = GetSettingProcessor("x", to="properties.z")
        exchange = _ex({})
        proc._apply_target(exchange, 456)
        assert exchange.properties["z"] == 456

    def test_apply_target_fallback(self) -> None:
        proc = GetSettingProcessor("x", to="other")
        exchange = _ex({})
        proc._apply_target(exchange, 789)
        assert exchange.properties["other"] == 789

    def test_apply_target_body_non_dict(self) -> None:
        proc = GetSettingProcessor("x", to="body.y")
        exchange = _ex("string")
        proc._apply_target(exchange, 123)
        assert exchange.in_message.body == {"y": 123}

    @pytest.mark.asyncio
    async def test_process_reads_setting(self) -> None:
        with patch(
            "src.backend.dsl.engine.processors.get_setting.GetSettingProcessor._read_setting",
            return_value="hello",
        ):
            proc = GetSettingProcessor("app.name", to="body.name")
            exchange = _ex({})
            await proc.process(exchange, None)  # type: ignore[arg-type]
            assert exchange.in_message.body == {"name": "hello"}

    def test_to_spec_defaults(self) -> None:
        proc = GetSettingProcessor("app.name")
        assert proc.to_spec() == {"get_setting": {"path": "app.name"}}

    def test_to_spec_with_options(self) -> None:
        proc = GetSettingProcessor("app.name", to="body.x", default="n/a")
        spec = proc.to_spec()
        assert spec == {
            "get_setting": {"path": "app.name", "to": "body.x", "default": "n/a"}
        }
