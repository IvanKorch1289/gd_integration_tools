"""Smoke-тесты K6 Wave 1: LangFuse v3 parallel shim (W11 GAP-AI finalized).

Покрывает:
- ``test_factory_returns_v3`` — фабрика возвращает v3-callback (default-ON).
- ``test_v3_callback_noop_without_langfuse`` — v3-callback silent при недоступном пакете.
- ``test_v3_callback_calls_span`` — v3-callback вызывает start_as_current_span.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

# ─── Тесты фабрики ──────────────────────────────────────────────────────────


def test_factory_returns_v3() -> None:
    """W11 GAP-AI: factory всегда возвращает v3-callback (default-ON, v2 удалён)."""
    from src.backend.services.ai.gateway.langfuse_callback_v3 import (
        LangFuseCallbackV3,
        get_langfuse_callback,
    )

    cb = get_langfuse_callback()
    assert isinstance(cb, LangFuseCallbackV3), (
        f"Expected LangFuseCallbackV3 (v3), got {type(cb).__name__}"
    )


# ─── Тесты v3 callback ──────────────────────────────────────────────────────


def test_v3_callback_noop_without_langfuse() -> None:
    """v3-callback не падает при недоступном пакете langfuse."""
    from src.backend.services.ai.gateway.langfuse_callback_v3 import LangFuseCallbackV3

    cb = LangFuseCallbackV3()
    # Симулируем отсутствие пакета: _inited=False, langfuse не установлен.
    # Подменяем langfuse импорт на ImportError.
    with patch.dict(sys.modules, {"langfuse": None}):
        # Сбросить кеш инициализации.
        cb._inited = False
        cb._lf = None
        # Вызов не должен падать.
        cb(kwargs={"model": "gpt-4o"}, response_obj={})


def test_v3_callback_calls_span() -> None:
    """v3-callback вызывает start_as_current_span и span.update с корректными данными."""
    from src.backend.services.ai.gateway.langfuse_callback_v3 import LangFuseCallbackV3

    # Подготовим mock LangFuse клиента.
    fake_span = MagicMock()
    fake_span.__enter__ = MagicMock(return_value=fake_span)
    fake_span.__exit__ = MagicMock(return_value=False)

    fake_client: Any = MagicMock()
    fake_client.start_as_current_span.return_value = fake_span

    cb = LangFuseCallbackV3()
    cb._lf = fake_client
    cb._inited = True

    response: dict[str, Any] = {
        "choices": [{"message": {"content": "ответ"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "response_cost": 0.002,
    }
    cb(
        kwargs={
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "привет"}],
            "metadata": {"tenant": "bank_ru", "route": "credit_check"},
        },
        response_obj=response,
        start_time="2026-05-13T10:00:00",
        end_time="2026-05-13T10:00:01",
    )

    # Проверяем, что span был создан с правильным именем трассы.
    fake_client.start_as_current_span.assert_called_once()
    call_kwargs = fake_client.start_as_current_span.call_args.kwargs
    assert call_kwargs["name"] == "llm.openai", (
        f"Expected name='llm.openai', got '{call_kwargs.get('name')}'"
    )

    # Проверяем, что span.update вызван с ключевыми полями.
    fake_span.update.assert_called_once()
    update_kwargs = fake_span.update.call_args.kwargs
    assert update_kwargs["model"] == "openai/gpt-4o-mini"
    assert update_kwargs["output"] == "ответ"
    assert update_kwargs["usage"] == {"input": 10, "output": 5, "total": 15}
    assert update_kwargs["metadata"]["tenant"] == "bank_ru"
    assert update_kwargs["metadata"]["cost_usd"] == 0.002
