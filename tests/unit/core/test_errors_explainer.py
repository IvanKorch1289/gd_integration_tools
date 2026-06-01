"""Tests for errors_explainer module (core/utils/errors_explainer.py).

Wave: [tech-debt/coverage].
Provides human-readable explanations for technical errors.
"""

from __future__ import annotations

from src.backend.core.errors_explainer import (
    ErrorExplainer,
    ExplainedError,
    explain_error,
    error_explainer,
)


class TestExplainError:
    """Tests for explain_error function."""

    def test_connection_refused_error(self) -> None:
        result = explain_error(ConnectionRefusedError("[Errno 111] Connection refused"))
        assert isinstance(result, ExplainedError)
        assert result.title == "Сервис недоступен"
        assert "Connection refused" in result.original

    def test_timeout_error(self) -> None:
        result = explain_error(TimeoutError("timed out"))
        assert isinstance(result, ExplainedError)
        assert result.title == "Превышен таймаут"

    def test_file_not_found_error(self) -> None:
        result = explain_error(FileNotFoundError("/path/to/file"))
        assert isinstance(result, ExplainedError)
        assert "FileNotFoundError" in result.title

    def test_permission_error(self) -> None:
        result = explain_error(PermissionError("Access denied"))
        assert isinstance(result, ExplainedError)
        assert "PermissionError" in result.title

    def test_unknown_error(self) -> None:
        result = explain_error(ValueError("some error"))
        assert isinstance(result, ExplainedError)
        assert "ValueError" in result.title


class TestErrorExplainerSingleton:
    """Tests for ErrorExplainer singleton."""

    def test_singleton_instance(self) -> None:
        """error_explainer should be a singleton instance."""
        assert isinstance(error_explainer, ErrorExplainer)

    def test_explain_delegates_to_global(self) -> None:
        """ErrorExplainer.explain should delegate to explain_error."""
        exp = ErrorExplainer()
        result = exp.explain(ConnectionRefusedError("test"))
        assert isinstance(result, ExplainedError)


class TestExplainedErrorDataclass:
    """Tests for ExplainedError dataclass fields."""

    def test_all_fields_present(self) -> None:
        error = ExplainedError(
            title="Test",
            what_happened="What happened",
            why="Why it happened",
            how_to_fix=["Step 1", "Step 2"],
            original="original error",
            docs_url="https://example.com/docs",
        )
        assert error.title == "Test"
        assert error.what_happened == "What happened"
        assert error.why == "Why it happened"
        assert error.how_to_fix == ["Step 1", "Step 2"]
        assert error.original == "original error"
        assert error.docs_url == "https://example.com/docs"

    def test_default_values(self) -> None:
        error = ExplainedError(
            title="Test",
            what_happened="What happened",
            why="Why",
            how_to_fix=[],
        )
        assert error.original == ""
        assert error.docs_url == ""


class TestErrorExplainerFallback:
    """Tests for ErrorExplainer fallback behavior."""

    def test_non_exception_string_input(self) -> None:
        """Non-Exception input should be handled gracefully."""
        explainer = ErrorExplainer()
        result = explainer.explain("some error string")
        assert isinstance(result, ExplainedError)
        assert result.title is not None

    def test_unknown_error_type(self) -> None:
        """Unknown error type should use fallback explanation."""
        explainer = ErrorExplainer()
        # Custom exception not in _ERROR_PATTERNS
        result = explainer.explain(RuntimeError("custom runtime error"))
        assert isinstance(result, ExplainedError)
        assert "RuntimeError" in result.title

    def test_fallback_explanation_content(self) -> None:
        """Fallback should provide helpful generic advice."""
        explainer = ErrorExplainer()
        result = explainer.explain(CustomError("test"))
        assert isinstance(result, ExplainedError)
        assert result.how_to_fix is not None
        assert len(result.how_to_fix) > 0


class CustomError(Exception):
    """Custom exception for testing."""
    pass
