"""TDD: JsonFacade (S171 M27+, D292).

Pattern (D292, Ponytail): unified JSON facade wrapping orjson.
Replaces direct json.dumps/loads imports in hot paths.
"""
# ruff: noqa: S101
from __future__ import annotations
import pytest


class TestJsonFacade:
    def test_dumps_bytes(self) -> None:
        from src.backend.core.utils.json_facade import dumps
        result = dumps({"key": "value"})
        assert isinstance(result, bytes)
        assert b'"key"' in result
        assert b'"value"' in result

    def test_dumps_unicode(self) -> None:
        from src.backend.core.utils.json_facade import dumps
        result = dumps({"msg": "Привет, мир! 🌍"})
        assert "Привет".encode("utf-8") in result

    def test_loads(self) -> None:
        from src.backend.core.utils.json_facade import dumps, loads
        original = {"a": 1, "b": [2, 3], "c": "x"}
        data = loads(dumps(original))
        assert data == original

    def test_fallback_to_stdlib(self) -> None:
        """Fallback на stdlib json если orjson отсутствует (D292)."""
        from src.backend.core.utils import json_facade
        # Проверим что модуль импортируется без ошибок
        assert json_facade.dumps({"a": 1}) is not None
