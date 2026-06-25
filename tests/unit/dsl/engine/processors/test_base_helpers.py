"""Tests for BaseProcessor.set_result helper (M2)."""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest


class TestSetResult:
    def test_body_field_creates_dict_if_missing(self) -> None:
        from src.backend.dsl.engine.processors.base import BaseProcessor

        class StubProcessor(BaseProcessor):
            async def process(self, exchange, context) -> None: ...

        p = StubProcessor(name="stub")
        ex = MagicMock()
        ex.in_message.body = None
        p.set_result(ex, "body.value", 42)
        assert ex.in_message.body == {"value": 42}

    def test_body_field_preserves_existing_body(self) -> None:
        from src.backend.dsl.engine.processors.base import BaseProcessor

        class StubProcessor(BaseProcessor):
            async def process(self, exchange, context) -> None: ...

        p = StubProcessor(name="stub")
        ex = MagicMock()
        ex.in_message.body = {"existing": "key"}
        p.set_result(ex, "body.new", "new_val")
        assert ex.in_message.body == {"existing": "key", "new": "new_val"}

    def test_properties_prefix_calls_set_property(self) -> None:
        from src.backend.dsl.engine.processors.base import BaseProcessor

        class StubProcessor(BaseProcessor):
            async def process(self, exchange, context) -> None: ...

        p = StubProcessor(name="stub")
        ex = MagicMock()
        p.set_result(ex, "properties.x", "y")
        ex.set_property.assert_called_once_with("x", "y")

    def test_plain_target_calls_set_property(self) -> None:
        from src.backend.dsl.engine.processors.base import BaseProcessor

        class StubProcessor(BaseProcessor):
            async def process(self, exchange, context) -> None: ...

        p = StubProcessor(name="stub")
        ex = MagicMock()
        p.set_result(ex, "result", "v")
        ex.set_property.assert_called_once_with("result", "v")
