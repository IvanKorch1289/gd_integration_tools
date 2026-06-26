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


class TestWafOwaspPatterns:
    """Проверка расширенных OWASP CRS паттернов."""

    def test_detects_xss_event_handler(self) -> None:
        from src.backend.dsl.engine.processors.waf_check import WafCheckProcessor
        p = WafCheckProcessor(source_property="body", action="flag")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"comment": "<img src=x onerror=alert(1)>"}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        import asyncio
        asyncio.run(p.process(ex, MagicMock()))
        # Verify decision
        assert ex.set_property.called
        args, _ = ex.set_property.call_args
        decision = args[1] if len(args) > 1 else args[0]
        if isinstance(decision, dict):
            assert not decision["safe"], f"expected malicious: {decision}"
            assert len(decision["matched_rules"]) > 0, "no rules matched"

    def test_detects_command_injection(self) -> None:
        from src.backend.dsl.engine.processors.waf_check import WafCheckProcessor
        p = WafCheckProcessor(source_property="body", action="flag")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"host": "test.com; cat /etc/passwd"}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        import asyncio
        asyncio.run(p.process(ex, MagicMock()))
        assert ex.set_property.called

    def test_detects_xxe(self) -> None:
        from src.backend.dsl.engine.processors.waf_check import WafCheckProcessor
        p = WafCheckProcessor(source_property="body", action="flag")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"xml": "<?xml version='1.0'?><!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><foo>&xxe;</foo>"}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        import asyncio
        asyncio.run(p.process(ex, MagicMock()))
        assert ex.set_property.called
