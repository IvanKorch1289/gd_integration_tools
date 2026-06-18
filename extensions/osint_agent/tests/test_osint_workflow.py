"""Tests for OSINT agent workflow."""

from __future__ import annotations

import pytest

from extensions.osint_agent.functions.osint_workflow import (
    _build_search_queries,
    _format_results,
    _parse_report_sections,
    compose_prompt,
    validate_inn,
    validate_report,
)


class TestValidateInn:
    """Tests for INN validation."""

    def test_valid_10_digit_inn(self) -> None:
        assert validate_inn("7707083893") is True

    def test_valid_12_digit_inn(self) -> None:
        assert validate_inn("770708389307") is True

    def test_invalid_inn_wrong_checksum(self) -> None:
        assert validate_inn("7707083890") is False

    def test_invalid_inn_letters(self) -> None:
        assert validate_inn("abc") is False

    def test_invalid_inn_wrong_length(self) -> None:
        assert validate_inn("12345") is False

    def test_empty_inn(self) -> None:
        assert validate_inn("") is False

    def test_none_inn(self) -> None:
        assert validate_inn(None) is False  # type: ignore[arg-type]


class TestBuildSearchQueries:
    """Tests for search query generation."""

    def test_basic_queries(self) -> None:
        queries = _build_search_queries("7707083893", "ООО Ромашка")
        assert "7707083893" in queries["general"]
        assert "ООО Ромашка" in queries["general"]
        assert "судебные" in queries["courts"]
        assert "жалобы" in queries["negative"]

    def test_empty_company_name(self) -> None:
        queries = _build_search_queries("7707083893", "")
        assert "7707083893" in queries["general"]


class TestFormatResults:
    """Tests for search results formatting."""

    def test_none_results(self) -> None:
        assert _format_results(None) == "Данные не найдены"

    def test_empty_list(self) -> None:
        assert _format_results([]) == "Данные не найдены"

    def test_dict_with_content(self) -> None:
        results = {"content": "Test content"}
        assert _format_results(results) == "Test content"

    def test_list_of_dicts(self) -> None:
        results = [{"content": "Result 1"}, {"content": "Result 2"}]
        formatted = _format_results(results)
        assert "Result 1" in formatted
        assert "Result 2" in formatted


class TestParseReportSections:
    """Tests for report section parsing."""

    def test_parse_full_report(self) -> None:
        raw = """\
═══════════════════════════════════════════════
ОТЧЁТ OSINT: Тест Компания
ИНН: 7707083893 | Дата: 2026-01-01
═══════════════════════════════════════════════

1. ОБЩАЯ ИНФОРМАЦИЯ
ООО Тест основана в 2020 году.

2. ПОЗИТИВНЫЕ УПОМИНАНИЯ
• Хорошие отзывы (источник: https://example.com)

3. НЕГАТИВНЫЕ УПОМИНАНИЯ / ЖАЛОБЫ
• Жалоба на сервис (источник: https://example.com)

4. СУДЕБНЫЕ ДЕЛА
• Дело № А40-12345 (источник: https://kad.arbitr.ru)

5. ФИНАНСОВЫЕ МАРКЕРЫ
• Выручка растёт

6. ИСТОЧНИКИ
[1] https://rusprofile.ru
[2] https://list-org.com

═══════════════════════════════════════════════"""
        sections = _parse_report_sections(raw)
        assert "Тест" in sections["general_info"]
        assert len(sections["positive_mentions"]) == 1
        assert len(sections["negative_mentions"]) == 1
        assert len(sections["court_cases"]) == 1
        assert len(sections["financial_markers"]) == 1
        assert len(sections["sources"]) == 2


class TestValidateReport:
    """Tests for report validation."""

    def test_truncates_long_report(self) -> None:
        long_text = "x" * 5000
        result = validate_report(long_text)
        assert len(result["raw_text"]) <= 3000

    def test_short_report_passes(self) -> None:
        short_text = "Short report"
        result = validate_report(short_text)
        assert result["raw_text"] == short_text


class TestComposePrompt:
    """Tests for prompt composition."""

    def test_prompt_contains_inn(self) -> None:
        prompt = compose_prompt(
            inn="7707083893",
            company_name="Тест",
            results_general=None,
            results_courts=None,
            results_negative=None,
        )
        assert "7707083893" in prompt
        assert "Тест" in prompt
