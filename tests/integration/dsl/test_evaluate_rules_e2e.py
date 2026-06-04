"""E2E тест .evaluate_rules() (Wave [wave:s8/k3-rule-engine-finale-tests-docs]).

Проверяет полный путь: пример ruleset из docs/dsl/rule-engine-example.yaml
→ парсинг → передача в processor → корректный action для типичных
скоринговых сценариев.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.rule_engine import (
    EvaluateRulesParams,
    EvaluateRulesProcessor,
    Rule,
)


_EXAMPLE_YAML = Path(__file__).parents[3] / "docs" / "dsl" / "rule-engine-example.yaml"


def _load_example_rules() -> tuple[list[Rule], str]:
    """Загружает пример credit_scoring и приводит его к contract'у processor'а.

    Сейчас scaffold-processor поддерживает поле ``decision`` (а пример из
    runbook — ``action``). E2E маппит ``action`` → ``decision`` и
    отбрасывает ``reason`` — это документирует ожидание для следующего
    шага миграции (когда processor расширится полем reason).
    """
    raw = yaml.safe_load(_EXAMPLE_YAML.read_text(encoding="utf-8"))
    rules: list[Rule] = []
    for entry in raw["rules"]:
        rules.append(
            Rule(name=entry["id"], expr=entry["condition"], decision=entry["action"])
        )
    return rules, raw.get("default_action", "approve")


def _make_exchange(body: Any) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.mark.asyncio
async def test_example_decline_on_low_score() -> None:
    """score=400 + debt_ratio=0.3 → high_risk_score → decline."""
    rules, default = _load_example_rules()
    proc = EvaluateRulesProcessor(
        EvaluateRulesParams(rules=rules, default_decision=default)
    )
    exchange = _make_exchange(
        body={"score": 400, "debt_ratio": 0.3, "income": 50000, "age": 30}
    )

    await proc.process(exchange, context=AsyncMock())

    assert exchange.in_message.body["decision"] == "decline"
    assert exchange.in_message.body["matched_rule"] == "high_risk_score"


@pytest.mark.asyncio
async def test_example_manual_review_on_mid_score() -> None:
    """score=600 + debt_ratio=0.3 → manual_review_band → manual_review."""
    rules, default = _load_example_rules()
    proc = EvaluateRulesProcessor(
        EvaluateRulesParams(rules=rules, default_decision=default)
    )
    exchange = _make_exchange(
        body={"score": 600, "debt_ratio": 0.3, "income": 50000, "age": 30}
    )

    await proc.process(exchange, context=AsyncMock())

    assert exchange.in_message.body["decision"] == "manual_review"


@pytest.mark.asyncio
async def test_example_approve_on_default() -> None:
    """score=800 + debt_ratio=0.2 → ни одно правило не сработало → approve."""
    rules, default = _load_example_rules()
    proc = EvaluateRulesProcessor(
        EvaluateRulesParams(rules=rules, default_decision=default)
    )
    exchange = _make_exchange(
        body={"score": 800, "debt_ratio": 0.2, "income": 80000, "age": 35}
    )

    await proc.process(exchange, context=AsyncMock())

    assert exchange.in_message.body["decision"] == "approve"
