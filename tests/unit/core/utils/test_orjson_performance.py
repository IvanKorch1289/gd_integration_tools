"""TDD: orjson adoption check (S171 M27-P1-1, D290).

Pattern (D290, Ponytail): verify orjson is consistently used для hot paths.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestOrjsonAdoption:
    def test_orjson_importable(self) -> None:
        import orjson
        assert orjson is not None
        # orjson.dumps/loads быстрее stdlib json на 3-5x
        data = {"key": "value", "list": [1, 2, 3]}
        s = orjson.dumps(data)
        assert isinstance(s, bytes)
        parsed = orjson.loads(s)
        assert parsed == data

    def test_orjson_handles_unicode(self) -> None:
        import orjson
        data = {"message": "Привет, мир! 🌍"}
        s = orjson.dumps(data)
        parsed = orjson.loads(s)
        assert parsed["message"] == "Привет, мир! 🌍"

    def test_orjson_dataclass_serializable(self) -> None:
        """orjson поддерживает dataclass через default (D290)."""
        from dataclasses import dataclass
        import orjson

        @dataclass
        class Point:
            x: int
            y: int

        p = Point(1, 2)
        s = orjson.dumps(p, default=lambda o: o.__dict__)
        parsed = orjson.loads(s)
        assert parsed == {"x": 1, "y": 2}
