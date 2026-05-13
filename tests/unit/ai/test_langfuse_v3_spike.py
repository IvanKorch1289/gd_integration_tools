"""Smoke-тесты K6 Wave 1: LangFuse v3 parallel shim под feature_flag.langfuse_v3.

Покрывает:
- ``test_factory_v2_when_flag_off`` — фабрика возвращает v2-callback при flag=False.
- ``test_factory_v3_when_flag_on`` — фабрика возвращает v3-callback при flag=True.
- ``test_v3_callback_noop_without_langfuse`` — v3-callback silent при недоступном пакете.
- ``test_v3_callback_calls_span`` — v3-callback вызывает start_as_current_span.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import MagicMock, patch


@contextmanager
def _patch_flag(value: bool) -> Generator[None, None, None]:
    """Контекст-менеджер для временной подмены feature_flags.langfuse_v3."""
    module_path = "src.backend.services.ai.gateway.langfuse_callback"
    with patch(f"{module_path}.feature_flags") as mock_flags:
        mock_flags.langfuse_v3 = value
        yield


# ─── Тесты фабрики ──────────────────────────────────────────────────────────


def test_factory_v2_when_flag_off() -> None:
    """При feature_flags.langfuse_v3=False фабрика возвращает v2-callback."""
    from src.backend.services.ai.gateway.langfuse_callback import (
        LangFuseCostCallback,
        get_langfuse_callback,
    )

    with _patch_flag(False):
        cb = get_langfuse_callback()

    assert isinstance(cb, LangFuseCostCallback), (
        f"Ожидался LangFuseCostCallback (v2), получен {type(cb).__name__}"
    )


def test_factory_v3_when_flag_on() -> None:
    """При feature_flags.langfuse_v3=True фабрика возвращает v3-callback."""
    from src.backend.services.ai.gateway.langfuse_callback_v3 import LangFuseCallbackV3

    with _patch_flag(True):
        from src.backend.services.ai.gateway.langfuse_callback import get_langfuse_callback

        cb = get_langfuse_callback()

    assert isinstance(cb, LangFuseCallbackV3), (
        f"Ожидался LangFuseCallbackV3 (v3), получен {type(cb).__name__}"
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
        f"Ожидалось name='llm.openai', получено '{call_kwargs.get('name')}'"
    )

    # Проверяем, что span.update вызван с ключевыми полями.
    fake_span.update.assert_called_once()
    update_kwargs = fake_span.update.call_args.kwargs
    assert update_kwargs["model"] == "openai/gpt-4o-mini"
    assert update_kwargs["output"] == "ответ"
    assert update_kwargs["usage"] == {"input": 10, "output": 5, "total": 15}
    assert update_kwargs["metadata"]["tenant"] == "bank_ru"
    assert update_kwargs["metadata"]["cost_usd"] == 0.002
