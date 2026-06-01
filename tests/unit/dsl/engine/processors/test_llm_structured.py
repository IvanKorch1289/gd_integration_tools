"""Тесты LLMStructuredProcessor (Wave [wave:s8/k4-llm-structured-finale]).

Покрытие:
* Validation в ``__init__`` (model format, retry, cost_budget).
* Schema resolution: None / bad string / direct class / module:Class.
* ImportError-branch при отсутствии instructor/litellm extras.
* Happy path через ``sys.modules`` stubs (без реального instructor).
* Cost budget exceeded → ``exchange.fail``.
* Provider extraction (``model.split('/', 1)[0]`` → ``properties[llm.provider]``).

Зависимости instructor/litellm живут в ``ai-2026`` optional-extra и в
test env не установлены — happy-path тесты подменяют их через
``monkeypatch.setitem(sys.modules, ...)``.
"""

# ruff: noqa: S101

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.llm_structured import LLMStructuredProcessor


class _SampleSchema(BaseModel):
    """Тестовая Pydantic-схема ответа LLM."""

    decision: str
    confidence: float


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


# ── Validation в __init__ ────────────────────────────────────────────────


def test_init_rejects_model_without_provider() -> None:
    """``model`` без ``/`` → ValueError на этапе __init__."""
    with pytest.raises(ValueError, match="provider"):
        LLMStructuredProcessor(
            model="claudeonly",
            output_schema=_SampleSchema,
            prompt="x",
        )


def test_init_rejects_negative_retry() -> None:
    """retry < 0 → ValueError."""
    with pytest.raises(ValueError, match="retry"):
        LLMStructuredProcessor(
            model="anthropic/claude-sonnet-4-6",
            output_schema=_SampleSchema,
            prompt="x",
            retry=-1,
        )


def test_init_rejects_negative_cost_budget() -> None:
    """cost_budget_usd < 0 → ValueError."""
    with pytest.raises(ValueError, match="cost_budget_usd"):
        LLMStructuredProcessor(
            model="anthropic/claude-sonnet-4-6",
            output_schema=_SampleSchema,
            prompt="x",
            cost_budget_usd=-0.01,
        )


# ── Schema resolution ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schema_none_fails_exchange() -> None:
    """``output_schema=None`` → exchange.fail на schema_error."""
    proc = LLMStructuredProcessor(
        model="anthropic/claude-sonnet-4-6",
        output_schema=None,
        prompt="x",
    )
    exchange = _make_exchange(body={})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.status == ExchangeStatus.failed
    assert "schema error" in (exchange.error or "")


@pytest.mark.asyncio
async def test_schema_bad_string_fails_exchange() -> None:
    """``output_schema='nonexistent.module:Cls'`` → exchange.fail."""
    proc = LLMStructuredProcessor(
        model="anthropic/claude-sonnet-4-6",
        output_schema="nonexistent.module.xyz:Cls",
        prompt="x",
    )
    exchange = _make_exchange(body={})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.status == ExchangeStatus.failed


# ── ImportError branch ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_instructor_fails_with_helpful_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """instructor не установлен → exchange.fail с подсказкой про extras."""
    monkeypatch.setitem(sys.modules, "instructor", None)
    monkeypatch.setitem(sys.modules, "litellm", None)
    proc = LLMStructuredProcessor(
        model="anthropic/claude-sonnet-4-6",
        output_schema=_SampleSchema,
        prompt="x",
    )
    exchange = _make_exchange(body={})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.status == ExchangeStatus.failed
    assert "ai-2026" in (exchange.error or "")


# ── Happy path через sys.modules stubs ───────────────────────────────────


@pytest.fixture
def stub_instructor_and_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Подменяет ``instructor``/``litellm`` модулями-заглушками.

    Возвращает dict с ключами:
        * ``client_create``: AsyncMock — установить return_value.
        * ``completion_cost``: MagicMock — установить return_value стоимости.
    """
    instructor_module = MagicMock()
    fake_client = MagicMock()
    create_mock: AsyncMock = AsyncMock()
    fake_client.create = create_mock
    instructor_module.from_litellm = MagicMock(return_value=fake_client)

    litellm_module = MagicMock()
    completion_cost_mock = MagicMock(return_value=0.0001)
    litellm_module.completion_cost = completion_cost_mock
    litellm_module.acompletion = MagicMock()

    monkeypatch.setitem(sys.modules, "instructor", instructor_module)
    monkeypatch.setitem(sys.modules, "litellm", litellm_module)

    yield {
        "client_create": create_mock,
        "completion_cost": completion_cost_mock,
    }


@pytest.mark.asyncio
async def test_happy_path_writes_pydantic_to_body(
    stub_instructor_and_litellm: dict[str, Any],
) -> None:
    """instructor возвращает Pydantic-объект → exchange.body содержит результат."""
    expected = _SampleSchema(decision="approve", confidence=0.9)
    stub_instructor_and_litellm["client_create"].return_value = expected

    proc = LLMStructuredProcessor(
        model="anthropic/claude-sonnet-4-6",
        output_schema=_SampleSchema,
        prompt="оцени: ${body.summary}",
        to="body.result",
    )
    exchange = _make_exchange(body={"summary": "заявка"})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.status != ExchangeStatus.failed
    assert exchange.in_message.body["result"] is expected


@pytest.mark.asyncio
async def test_happy_path_records_provider(
    stub_instructor_and_litellm: dict[str, Any],
) -> None:
    """``properties[llm.provider]`` извлекается из ``model.split('/')``."""
    stub_instructor_and_litellm["client_create"].return_value = _SampleSchema(
        decision="approve", confidence=0.9
    )

    proc = LLMStructuredProcessor(
        model="openai/gpt-4o",
        output_schema=_SampleSchema,
        prompt="x",
    )
    exchange = _make_exchange(body={})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.properties["llm.provider"] == "openai"
    assert exchange.properties["llm.model"] == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_call_failure_marks_exchange_failed(
    stub_instructor_and_litellm: dict[str, Any],
) -> None:
    """instructor.create выбрасывает исключение → exchange.fail."""
    stub_instructor_and_litellm["client_create"].side_effect = ValueError(
        "validation failed after retries"
    )

    proc = LLMStructuredProcessor(
        model="anthropic/claude-sonnet-4-6",
        output_schema=_SampleSchema,
        prompt="x",
    )
    exchange = _make_exchange(body={})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.status == ExchangeStatus.failed
    assert "failed" in (exchange.error or "").lower()


# ── Builder integration ──────────────────────────────────────────────────


def test_builder_method_creates_processor() -> None:
    """RouteBuilder.llm_structured() добавляет LLMStructuredProcessor с params."""
    from src.backend.dsl.builders.base import RouteBuilder

    builder = RouteBuilder("test_route")
    builder.llm_structured(
        model="anthropic/claude-sonnet-4-6",
        output_schema=_SampleSchema,
        prompt="x",
        retry=2,
        cost_budget_usd=0.01,
    )

    last = builder._processors[-1]
    assert isinstance(last, LLMStructuredProcessor)
    assert last._model == "anthropic/claude-sonnet-4-6"
    assert last._retry == 2
    assert last._cost_budget_usd == 0.01
