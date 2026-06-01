# ruff: noqa: S101
"""Unit-тесты функций нормализации credit_pipeline (Sprint 7 Team T3).

Wave: ``[wave:s7/team-03-credit-1st-client]``.

Покрытие:
* apply_rules: normalize score + risk_class + decision-cast;
* calculate_combined_score: weighted average SKB(0.6) + НБКИ(0.4).
"""

from __future__ import annotations

from extensions.credit_pipeline.functions.normalize import (
    apply_rules,
    calculate_combined_score,
)


def test_apply_rules_low_risk_score_above_700() -> None:
    """``score >= 700`` → ``risk_class=LOW``."""
    result = apply_rules({"score": 720, "decision": "APPROVE"})
    assert result["score"] == 720
    assert result["risk_class"] == "LOW"
    assert result["decision"] == "APPROVE"


def test_apply_rules_medium_risk_score_between_500_700() -> None:
    """``500 <= score < 700`` → ``risk_class=MEDIUM``."""
    result = apply_rules({"score": 600})
    assert result["risk_class"] == "MEDIUM"


def test_apply_rules_high_risk_low_score() -> None:
    """``score < 500`` → ``risk_class=HIGH``."""
    result = apply_rules({"score": 300})
    assert result["risk_class"] == "HIGH"


def test_apply_rules_clips_score_to_range() -> None:
    """Score за пределами ``[0, 1000]`` обрезается."""
    assert apply_rules({"score": 1500})["score"] == 1000
    assert apply_rules({"score": -100})["score"] == 0


def test_apply_rules_decision_cast_to_string() -> None:
    """Не-строковый ``decision`` приводится к строке."""
    result = apply_rules({"decision": 1})
    assert result["decision"] == "1"


def test_apply_rules_missing_score_does_not_raise() -> None:
    """Отсутствующий ``score`` не вызывает ошибки."""
    result = apply_rules({"name": "test"})
    assert "risk_class" not in result
    assert result["name"] == "test"


def test_calculate_combined_score_both_providers() -> None:
    """SKB(800)*0.6 + НБКИ(700)*0.4 = 760."""
    assert calculate_combined_score(800, 700) == 760


def test_calculate_combined_score_only_skb() -> None:
    """Только SKB-score — вернуть его без weighting (1 источник)."""
    assert calculate_combined_score(800, None) == 800


def test_calculate_combined_score_only_nbki() -> None:
    """Только НБКИ-score — вернуть его без weighting."""
    assert calculate_combined_score(None, 700) == 700


def test_calculate_combined_score_neither() -> None:
    """Ни одного score — 0 (без падения)."""
    assert calculate_combined_score(None, None) == 0
