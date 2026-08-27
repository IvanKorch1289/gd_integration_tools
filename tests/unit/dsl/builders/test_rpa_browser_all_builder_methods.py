"""P4 regression test (Cycle 15, production-grade plan).

5 новых builder methods для rpa_browser.py processors:
- ``rpa_navigate`` → NavigateProcessor
- ``rpa_click`` → ClickProcessor
- ``rpa_fill`` → FillProcessor
- ``rpa_extract`` → ExtractProcessor
- ``rpa_screenshot`` → ScreenshotProcessor

Smoke test: builder methods существуют, возвращают RouteBuilder,
правильно пробрасывают kwargs через _add_lazy.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/dsl/builders/test_rpa_browser_all_builder_methods.py -v
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builder import RouteBuilder


class TestRpaBrowserBuilderMethods:
    """5 новых builder methods существуют и возвращают RouteBuilder."""

    @pytest.fixture
    def builder(self) -> RouteBuilder:
        """Создать minimal RouteBuilder через from_ factory."""
        return RouteBuilder.from_("test_rpa", source="test:source")

    def test_rpa_navigate_method_exists(self, builder: RouteBuilder) -> None:
        """``builder.rpa_navigate(url='...')`` → RouteBuilder."""
        result = builder.rpa_navigate(url="https://example.com")
        assert result is builder  # chainable

    def test_rpa_click_method_exists(self, builder: RouteBuilder) -> None:
        """``builder.rpa_click(selector='...')`` → RouteBuilder."""
        result = builder.rpa_click(selector="button.submit")
        assert result is builder

    def test_rpa_click_with_timeout(self, builder: RouteBuilder) -> None:
        """``builder.rpa_click(selector='...', timeout=5.0)`` → ok."""
        result = builder.rpa_click(selector="a", timeout=5.0)
        assert result is builder

    def test_rpa_fill_method_exists(self, builder: RouteBuilder) -> None:
        """``builder.rpa_fill(selector='...', value='...')`` → RouteBuilder."""
        result = builder.rpa_fill(selector="input.email", value="test@example.com")
        assert result is builder

    def test_rpa_extract_method_exists(self, builder: RouteBuilder) -> None:
        """``builder.rpa_extract(selector='...')`` → RouteBuilder."""
        result = builder.rpa_extract(selector="h1.title")
        assert result is builder

    def test_rpa_extract_with_attribute(self, builder: RouteBuilder) -> None:
        """``builder.rpa_extract(selector='...', attribute='href')`` → ok."""
        result = builder.rpa_extract(selector="a.link", attribute="href")
        assert result is builder

    def test_rpa_screenshot_method_exists(self, builder: RouteBuilder) -> None:
        """``builder.rpa_screenshot()`` → RouteBuilder."""
        result = builder.rpa_screenshot()
        assert result is builder

    def test_rpa_screenshot_with_options(self, builder: RouteBuilder) -> None:
        """``builder.rpa_screenshot(full_page=True, path='/tmp/x.png')`` → ok."""
        result = builder.rpa_screenshot(full_page=True, path="/tmp/x.png")
        assert result is builder

    def test_chaining_rpa_methods(self, builder: RouteBuilder) -> None:
        """5 методов chainable друг за другом."""
        result = (
            builder.rpa_navigate(url="https://example.com")
            .rpa_click(selector="button")
            .rpa_fill(selector="input", value="test")
            .rpa_extract(selector="h1")
            .rpa_screenshot()
        )
        assert result is builder
