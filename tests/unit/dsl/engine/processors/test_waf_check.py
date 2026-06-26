"""TDD: WafCheckProcessor — DSL обёртка над core/net/waf."""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest


class TestWafCheckProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.waf_check import (
            WafCheckProcessor,
        )
        p = WafCheckProcessor(
            source_property="body.request",
            action="block",
        )
        assert p.action == "block"

    @pytest.mark.asyncio
    async def test_blocks_malicious_request(self) -> None:
        from src.backend.dsl.engine.processors.waf_check import (
            WafCheckProcessor,
        )
        p = WafCheckProcessor(
            source_property="body",
            action="block",
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"path": "/admin/../etc/passwd"}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert ex.set_property.called or ex.set_error.called
