"""Unit-тесты для DSL ``evaluate_rules`` процессора.

Wave ``[wave:s8/rule-engine-scaffold]``. Покрытие:

* first-match-wins (несколько подходящих правил — берётся первое).
* default_decision если ни одно правило не сработало.
* битое выражение в правиле пропускается, остальные обрабатываются.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.rule_engine import (
    EvaluateRulesParams,
    EvaluateRulesProcessor,
    Rule,
)


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.mark.asyncio
async def test_first_match_wins_returns_decision() -> None:
    proc = EvaluateRulesProcessor(
        EvaluateRulesParams(
            rules=[
                Rule(name="approve", expr="score > 700", decision="APPROVE"),
                Rule(name="manual", expr="score > 500", decision="MANUAL"),
            ],
            context_from="applicant",
            decision_to="decision",
        )
    )
    exchange = _make_exchange(body={"applicant": {"score": 720}})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.in_message.body["decision"] == "APPROVE"
    assert exchange.in_message.body["matched_rule"] == "approve"


@pytest.mark.asyncio
async def test_default_decision_when_no_rule_matches() -> None:
    proc = EvaluateRulesProcessor(
        EvaluateRulesParams(
            rules=[
                Rule(name="approve", expr="score > 700", decision="APPROVE"),
            ],
            context_from=None,
            decision_to="decision",
            default_decision="REJECT",
        )
    )
    exchange = _make_exchange(body={"score": 100})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.in_message.body["decision"] == "REJECT"
    assert "matched_rule" not in exchange.in_message.body


@pytest.mark.asyncio
async def test_broken_rule_is_skipped_others_evaluated() -> None:
    proc = EvaluateRulesProcessor(
        EvaluateRulesParams(
            rules=[
                Rule(
                    name="broken",
                    expr="undefined_var > 0",
                    decision="SHOULD_NOT_FIRE",
                ),
                Rule(name="ok", expr="score == 50", decision="OK"),
            ],
            decision_to="decision",
            default_decision="FALLBACK",
        )
    )
    exchange = _make_exchange(body={"score": 50})

    await proc.process(exchange, context=AsyncMock())

    assert exchange.in_message.body["decision"] == "OK"
    assert exchange.in_message.body["matched_rule"] == "ok"
