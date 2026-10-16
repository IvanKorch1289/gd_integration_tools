"""Unit-тесты для ``src.backend.services.ai.usage_meter``.

Audit re-audit (2026-10-15) priority 7: «Поднять coverage критичных
ветвей — services/infrastructure/plugins растут без фиктивных тестов».
``usage_meter.py`` (110 LOC) содержит ``UsageStats`` + ``extract_usage``
— pure-Python data transformation logic без external deps.
Раньше unit-тестов не было, только indirect coverage через
ai_graph/ai_agent integration tests.

Тесты проверяют:

1. ``UsageStats.total_tokens`` — property arithmetic;
2. ``extract_usage`` из dict-ответа OpenAI;
3. ``extract_usage`` из pydantic-объекта (litellm.ModelResponse);
4. ``extract_usage`` с None usage → нули;
5. ``extract_usage`` с mixed dict/object usage;
6. ``extract_usage`` с non-int полями (None, str) → int coercion
   (default 0);
7. Frozen dataclass нельзя mutate.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.services.ai.usage_meter import UsageStats, extract_usage

# ─────────────────────────── UsageStats ───────────────────────────


class TestUsageStats:
    """``UsageStats`` — нормализованная статистика usage."""

    def test_total_tokens_sums_prompt_and_completion(self) -> None:
        """prompt + completion = total."""
        stats = UsageStats(prompt_tokens=100, completion_tokens=50)
        assert stats.total_tokens == 150

    def test_total_tokens_with_zero_prompt(self) -> None:
        """Edge case: только completion tokens."""
        stats = UsageStats(prompt_tokens=0, completion_tokens=42)
        assert stats.total_tokens == 42

    def test_frozen_dataclass_prevents_mutation(self) -> None:
        """``UsageStats`` — frozen, нельзя mutate."""
        stats = UsageStats(prompt_tokens=10, completion_tokens=20)
        with pytest.raises((FrozenInstanceError, AttributeError)):
            stats.prompt_tokens = 999  # type: ignore[misc]

    def test_slots_prevent_extra_attributes(self) -> None:
        """``__slots__`` — нельзя добавить extra fields.

        Python 3.14: слот-классы бросают ``TypeError`` (а не ``AttributeError``
        как в более старых версиях) при попытке set не-existing атрибута.
        Проверяем ОБОИХ — тест совместим с py3.12+ и py3.14+.
        """
        stats = UsageStats(prompt_tokens=10, completion_tokens=20)
        with pytest.raises((AttributeError, TypeError)):
            stats.extra_field = 999  # type: ignore[attr-defined]


# ─────────────────────────── extract_usage ───────────────────────────


class TestExtractUsage:
    """``extract_usage`` — нормализация usage из разных LLM response форматов."""

    def test_dict_response_with_full_usage(self) -> None:
        """OpenAI-style dict response с полным usage."""
        response = {
            "id": "chatcmpl-1",
            "choices": [...],  # choices НЕ нужны для usage
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
        stats = extract_usage(response)
        assert stats.prompt_tokens == 100
        assert stats.completion_tokens == 50
        assert stats.total_tokens == 150

    def test_dict_response_with_missing_usage(self) -> None:
        """Dict response без usage → нули (не падает)."""
        response = {"id": "chatcmpl-1", "choices": []}
        stats = extract_usage(response)
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0
        assert stats.total_tokens == 0

    def test_dict_response_with_none_usage(self) -> None:
        """Dict response с usage=None → нули."""
        response = {"id": "chatcmpl-1", "usage": None}
        stats = extract_usage(response)
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0

    def test_dict_response_with_partial_usage(self) -> None:
        """Dict response с usage но без prompt_tokens → defaults 0."""
        response = {
            "usage": {
                "completion_tokens": 50
                # no prompt_tokens
            }
        }
        stats = extract_usage(response)
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 50
        assert stats.total_tokens == 50

    def test_pydantic_object_response(self) -> None:
        """litellm.ModelResponse-style object с .usage attribute."""
        usage_obj = SimpleNamespace(prompt_tokens=200, completion_tokens=100)
        response = SimpleNamespace(usage=usage_obj, id="obj-1")
        stats = extract_usage(response)
        assert stats.prompt_tokens == 200
        assert stats.completion_tokens == 100
        assert stats.total_tokens == 300

    def test_pydantic_object_without_usage(self) -> None:
        """Object response без .usage attribute → нули."""
        response = SimpleNamespace(id="obj-no-usage")
        stats = extract_usage(response)
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0

    def test_pydantic_object_with_none_usage(self) -> None:
        """Object response с .usage=None → нули."""
        response = SimpleNamespace(usage=None, id="obj-1")
        stats = extract_usage(response)
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0

    def test_pydantic_usage_with_missing_fields(self) -> None:
        """Object usage без prompt_tokens/completion_tokens → defaults 0."""
        usage_obj = SimpleNamespace()  # пустой
        response = SimpleNamespace(usage=usage_obj)
        stats = extract_usage(response)
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0

    @pytest.mark.parametrize(
        "raw_prompt,raw_completion,expected_prompt,expected_completion",
        [
            (None, None, 0, 0),  # None → 0
            ("100", "50", 0, 0),  # str не int → int() упадёт
            # Use sentinel: dict.get returns None, code does `or 0` → 0
            (0, 0, 0, 0),  # явные нули
            (1, 2, 1, 2),  # минимальные positive
        ],
    )
    def test_int_coercion_and_none_handling(
        self,
        raw_prompt: Any,
        raw_completion: Any,
        expected_prompt: int,
        expected_completion: int,
    ) -> None:
        """None/str значения обрабатываются через ``or 0`` (None)
        или ``int()`` coercion. Str не конвертится (int('100')=100,
        но мы не падаем — поведение зависит от int() coercion)."""
        response = {
            "usage": {"prompt_tokens": raw_prompt, "completion_tokens": raw_completion}
        }
        if raw_prompt == "100":
            # int("100") works → ожидаем 100; raw_completion="50" → 50
            stats = extract_usage(response)
            assert stats.prompt_tokens == 100
            assert stats.completion_tokens == 50
        elif raw_prompt is None or raw_prompt == 0 or raw_prompt == 1:
            stats = extract_usage(response)
            assert stats.prompt_tokens == expected_prompt
            assert stats.completion_tokens == expected_completion

    def test_pydantic_partial_usage(self) -> None:
        """Object usage с одним полем — другое default 0."""
        usage_obj = SimpleNamespace(prompt_tokens=42)  # no completion_tokens
        response = SimpleNamespace(usage=usage_obj)
        stats = extract_usage(response)
        assert stats.prompt_tokens == 42
        assert stats.completion_tokens == 0
