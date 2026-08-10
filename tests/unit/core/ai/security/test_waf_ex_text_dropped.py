"""Regression tests for WAF processor: removed ``ex_text`` dead variable.

S108/F841 audit: ``waf_check.py:124`` had an unused ``ex_text`` local. The
fix drops the variable entirely; we verify the processor still blocks
matches and sets the decision without crashing.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.processors.waf_check import WafCheckProcessor

from typing import Any  # Cycle-19 (D-AUDIT-1908): runtime Any для monkeypatch callbacks


class TestWafExTextRegression:
    @pytest.mark.asyncio
    async def test_block_action_calls_stop_when_matched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After the ``ex_text`` dead variable was removed, the
        ``block`` branch must still terminate the exchange via
        ``exchange.stop()`` and emit the decision."""
        p = WafCheckProcessor(
            source_property="body.text",
            action="block",
        )

        async def _ok(*_a: Any, **_kw: Any) -> bool:
            return True

        monkeypatch.setattr(p, "auth_check", _ok)

        captured: dict[str, Any] = {}

        def _set_result(exch: Any, target: str, value: Any) -> None:
            captured["target"] = target
            captured["value"] = value

        monkeypatch.setattr(p, "set_result", _set_result)

        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"text": "<script>alert(1)</script>"}
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())

        ex.stop.assert_called_once()
        assert captured["value"]["safe"] is False
        assert any("xss_script_tag" in r for r in captured["value"]["matched_rules"])

    @pytest.mark.asyncio
    async def test_no_match_does_not_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = WafCheckProcessor(
            source_property="body.text",
            action="block",
        )

        async def _ok(*_a: Any, **_kw: Any) -> bool:
            return True

        monkeypatch.setattr(p, "auth_check", _ok)
        monkeypatch.setattr(p, "set_result", lambda *a, **kw: None)

        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"text": "clean input"}
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        ex.stop.assert_not_called()
