# ruff: noqa: S101
"""Tests for OSINT agent workflow."""

from __future__ import annotations

import pytest

from extensions.osint_agent.functions.osint_workflow import (
    InsufficientDataError,
    LLMUnavailableError,
    _all_search_results_empty,
    _build_search_queries,
    _format_results,
    _parse_report_sections,
    compose_prompt,
    run_osint,
    validate_inn,
    validate_report,
)


class TestValidateInn:
    """Tests for INN validation."""

    def test_valid_10_digit_inn(self) -> None:
        """Test: valid 10 digit inn."""
        assert validate_inn("7707083893") is True

    def test_valid_12_digit_inn(self) -> None:
        """Test: valid 12 digit inn."""
        assert validate_inn("770708389307") is True

    def test_invalid_inn_wrong_checksum(self) -> None:
        """Test: invalid inn wrong checksum."""
        assert validate_inn("7707083890") is False

    def test_invalid_inn_letters(self) -> None:
        """Test: invalid inn letters."""
        assert validate_inn("abc") is False

    def test_invalid_inn_wrong_length(self) -> None:
        """Test: invalid inn wrong length."""
        assert validate_inn("12345") is False

    def test_empty_inn(self) -> None:
        """Test: empty inn."""
        assert validate_inn("") is False

    def test_none_inn(self) -> None:
        """Test: none inn."""
        assert validate_inn(None) is False  # type: ignore[arg-type]


class TestBuildSearchQueries:
    """Tests for search query generation."""

    def test_basic_queries(self) -> None:
        """Test: basic queries."""
        queries = _build_search_queries("7707083893", "ООО Ромашка")
        assert "7707083893" in queries["general"]
        assert "ООО Ромашка" in queries["general"]
        assert "судебные" in queries["courts"]
        assert "жалобы" in queries["negative"]

    def test_empty_company_name(self) -> None:
        """Test: empty company name."""
        queries = _build_search_queries("7707083893", "")
        assert "7707083893" in queries["general"]


class TestFormatResults:
    """Tests for search results formatting."""

    def test_none_results(self) -> None:
        """Test: none results."""
        assert _format_results(None) == "Данные не найдены"

    def test_empty_list(self) -> None:
        """Test: empty list."""
        assert _format_results([]) == "Данные не найдены"

    def test_dict_with_content(self) -> None:
        """Test: dict with content."""
        results = {"content": "Test content"}
        assert _format_results(results) == "Test content"

    def test_list_of_dicts(self) -> None:
        """Test: list of dicts."""
        results = [{"content": "Result 1"}, {"content": "Result 2"}]
        formatted = _format_results(results)
        assert "Result 1" in formatted
        assert "Result 2" in formatted


class TestParseReportSections:
    """Tests for report section parsing."""

    def test_parse_full_report(self) -> None:
        """Test: parse full report."""
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
        """Test: truncates long report."""
        long_text = "x" * 5000
        result = validate_report(long_text)
        assert len(result["raw_text"]) <= 3000

    def test_short_report_passes(self) -> None:
        """Test: short report passes."""
        short_text = "Short report"
        result = validate_report(short_text)
        assert result["raw_text"] == short_text


class TestComposePrompt:
    """Tests for prompt composition."""

    def test_prompt_contains_inn(self) -> None:
        """Test: prompt contains inn."""
        prompt = compose_prompt(
            inn="7707083893",
            company_name="Тест",
            results_general=None,
            results_courts=None,
            results_negative=None,
        )
        assert "7707083893" in prompt
        assert "Тест" in prompt


class TestAllSearchResultsEmpty:
    """cycle-5/D-AUDIT-503 (BL-P0-002): helper для fail-CLOSED до LLM-вызова."""

    def test_all_none_is_empty(self) -> None:
        """Test: all None providers → empty."""
        assert _all_search_results_empty(
            {"perplexity": None, "tavily": None, "scraped": []},
            {"perplexity": None, "tavily": None, "scraped": []},
            {"perplexity": None, "tavily": None, "scraped": []},
        ) is True

    def test_one_provider_with_data_is_not_empty(self) -> None:
        """Test: если хотя бы один провайдер дал данные → not empty."""
        assert _all_search_results_empty(
            {"perplexity": [{"content": "data"}], "tavily": [], "scraped": []},
            {"perplexity": None, "tavily": None, "scraped": []},
            {"perplexity": None, "tavily": None, "scraped": []},
        ) is False

    def test_non_dict_arg_is_not_empty(self) -> None:
        """Test: не-dict результат (аномалия) → not empty (defensive)."""
        assert _all_search_results_empty(None, None, None) is False

    def test_empty_dict_treated_as_empty(self) -> None:
        """Test: пустые {} для каждого провайдера → empty."""
        assert _all_search_results_empty(
            {"perplexity": {}, "tavily": {}, "scraped": []},
            {"perplexity": {}, "tavily": {}, "scraped": []},
            {"perplexity": {}, "tavily": {}, "scraped": []},
        ) is True


class TestRunOsintFailClosed:
    """cycle-5/D-AUDIT-503: fail-CLOSED contract для OSINT."""

    @pytest.mark.asyncio
    async def test_llm_failure_raises_unavailable_no_template_echo(self) -> None:
        """BL-P0-001: LLM failure → LLMUnavailableError, НЕ raw_text=prompt.

        Mock search возвращает реальные данные (чтобы пройти pre-LLM guard),
        mock LLM бросает exception. Verify: raise LLMUnavailableError,
        result НЕ содержит prompt template.
        """
        from unittest.mock import AsyncMock, patch

        fake_search_results = {
            "perplexity": [{"content": "Some real data"}],
            "tavily": [],
            "scraped": [],
        }

        async def fake_search(query: str, *, max_results: int = 10) -> dict:
            return fake_search_results

        async def failing_acompletion(*args: object, **kwargs: object) -> dict:
            raise RuntimeError("LLM gateway down")

        with patch(
            "extensions.osint_agent.functions.osint_workflow._search_multi_provider",
            new=AsyncMock(side_effect=fake_search),
        ):
            with patch(
                "src.backend.core.ai.llm_gateway.get_litellm_gateway",
                return_value=type("G", (), {"acompletion": failing_acompletion})(),
            ):
                with pytest.raises(LLMUnavailableError) as exc_info:
                    await run_osint({"inn": "7707083893", "company_name": "Test"})
                # Verify: error message не содержит "OSINT_REPORT_TEMPLATE"
                # (никакого prompt-echo как report).
                assert "OSINT_REPORT_TEMPLATE" not in str(exc_info.value)
                assert "7707083893" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_search_results_raises_insufficient_data_no_llm(self) -> None:
        """BL-P0-002: пустые search results → InsufficientDataError, LLM НЕ вызван."""
        from unittest.mock import AsyncMock, patch

        empty_results = {"perplexity": None, "tavily": None, "scraped": []}

        async def fake_search(query: str, *, max_results: int = 10) -> dict:
            return empty_results

        llm_called = False

        async def tracking_acompletion(*args: object, **kwargs: object) -> dict:
            nonlocal llm_called
            llm_called = True
            return {"choices": [{"message": {"content": "HALLUCINATED"}}]}

        with patch(
            "extensions.osint_agent.functions.osint_workflow._search_multi_provider",
            new=AsyncMock(side_effect=fake_search),
        ):
            with patch(
                "src.backend.core.ai.llm_gateway.get_litellm_gateway",
                return_value=type("G", (), {"acompletion": tracking_acompletion})(),
            ):
                with pytest.raises(InsufficientDataError) as exc_info:
                    await run_osint({"inn": "7707083893", "company_name": "Test"})
                # Verify: LLM НЕ был вызван (fail-CLOSED guard).
                assert llm_called is False, "LLM должен быть skip при empty search"
                # Verify: error message содержит INN.
                assert "7707083893" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_search_failure_initializes_empty_then_insufficient_data(self) -> None:
        """Outer except → dicts с None, далее fail-CLOSED InsufficientDataError."""
        from unittest.mock import AsyncMock, patch

        async def failing_search(query: str, *, max_results: int = 10) -> dict:
            raise ConnectionError("search provider down")

        with patch(
            "extensions.osint_agent.functions.osint_workflow._search_multi_provider",
            new=AsyncMock(side_effect=failing_search),
        ):
            with pytest.raises(InsufficientDataError):
                await run_osint({"inn": "7707083893", "company_name": "Test"})

    @pytest.mark.asyncio
    async def test_partial_results_one_provider_has_data_passes_guard(self) -> None:
        """Если ОДИН провайдер дал данные (across 3 queries) → НЕ insufficient.

        Guard требует _all_ search results empty. Если хоть один результат
        содержит данные — fail-CLOSED guard не срабатывает, LLM вызывается.
        """
        from unittest.mock import AsyncMock, patch

        call_count = 0

        async def variable_search(query: str, *, max_results: int = 10) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # courts query has data
                return {"perplexity": [{"content": "court data"}], "tavily": [], "scraped": []}
            return {"perplexity": None, "tavily": None, "scraped": []}

        async def good_acompletion(*args: object, **kwargs: object) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "1. ОБЩАЯ ИНФОРМАЦИЯ\n"
                                "Test info.\n\n"
                                "6. ИСТОЧНИКИ\n"
                                "[1] https://example.com"
                            )
                        }
                    }
                ]
            }

        with patch(
            "extensions.osint_agent.functions.osint_workflow._search_multi_provider",
            new=AsyncMock(side_effect=variable_search),
        ):
            with patch(
                "src.backend.core.ai.llm_gateway.get_litellm_gateway",
                return_value=type("G", (), {"acompletion": good_acompletion})(),
            ):
                # Не должно быть InsufficientDataError, должен вернуться report.
                result = await run_osint({"inn": "7707083893", "company_name": "Test"})
                assert "inn" in result
                assert result["inn"] == "7707083893"
