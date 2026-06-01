"""Тесты LangFuseCallbackV3 (W11 GAP-AI: v2 removed).

v2-тесты (LangFuseCostCallback) удалены — их эквиваленты есть в
test_langfuse_v3_spike.py. Здесь только v3-специфичные smoke-тесты.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_callback_v3_noop_when_client_unavailable() -> None:
    """v3 callback не падает когда langfuse клиент недоступен."""
    from src.backend.services.ai.gateway.langfuse_callback_v3 import LangFuseCallbackV3

    cb = LangFuseCallbackV3()
    cb(kwargs={"model": "gpt-4o-mini"}, response_obj={"choices": []})
    # без исключения — OK
