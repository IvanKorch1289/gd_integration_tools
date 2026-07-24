"""M7: tests для Pydantic-based LLM-judge JSON parsing (замена кастомного extraction).

Покрывает ``_JudgeResponse.model_validate_json`` — type-safe parsing
с permissive defaults (отсутствующие поля → тихий default, как раньше).

Без regression: те же defaults, тот же fallback chain, тот же
``verdict="error"`` path для структурных поломок.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.services.ai.llm_judge import _JudgeResponse


class TestJudgeResponseParsing:
    """Type-safe extraction для LLM-judge JSON."""

    def test_full_response(self) -> None:
        """Все поля присутствуют → strict pass-through."""
        r = _JudgeResponse.model_validate_json(
            '{"hallucination": 0.2, "relevance": 0.9, "toxicity": 0.0, '
            '"verdict": "ok", "explanation": "good"}'
        )
        assert r.hallucination == 0.2
        assert r.relevance == 0.9
        assert r.toxicity == 0.0
        assert r.verdict == "ok"
        assert r.explanation == "good"

    def test_missing_fields_use_defaults(self) -> None:
        """Частичный JSON → permissive defaults (без regression)."""
        r = _JudgeResponse.model_validate_json('{"hallucination": 0.5}')
        assert r.hallucination == 0.5
        assert r.relevance == 0.0  # default
        assert r.toxicity == 0.0
        assert r.verdict == "unknown"
        assert r.explanation == ""

    def test_string_coerced_to_float(self) -> None:
        """LLM иногда возвращает числа как строки — Pydantic coerce."""
        r = _JudgeResponse.model_validate_json(
            '{"hallucination": "0.3", "relevance": "0.8", "toxicity": "0"}'
        )
        assert r.hallucination == 0.3
        assert r.relevance == 0.8
        assert r.toxicity == 0.0

    def test_extra_fields_ignored(self) -> None:
        """LLM может вернуть лишние поля — игнорируем без ошибки."""
        r = _JudgeResponse.model_validate_json(
            '{"hallucination": 0.1, "reasoning": "abc", "model_notes": "x"}'
        )
        assert r.hallucination == 0.1

    def test_invalid_json_raises_validation_error(self) -> None:
        """Невалидный JSON → ValidationError (caught outer try/except → error verdict)."""
        with pytest.raises((ValidationError, ValueError)):
            _JudgeResponse.model_validate_json("not json at all")

    def test_non_dict_json_raises(self) -> None:
        """JSON-list или скаляр → ошибка парсинга."""
        with pytest.raises((ValidationError, ValueError)):
            _JudgeResponse.model_validate_json("[1, 2, 3]")

    def test_null_verdict_falls_back_to_unknown(self) -> None:
        """``verdict: null`` → default ``"unknown"``."""
        r = _JudgeResponse.model_validate_json('{"verdict": null}')
        assert r.verdict == "unknown"
