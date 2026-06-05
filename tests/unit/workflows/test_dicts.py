"""Unit tests for src.backend.workflows.dicts."""

from __future__ import annotations

import pytest

from src.backend.workflows.dicts import ProcessingResult


@pytest.mark.unit
class TestProcessingResult:
    def test_success_case(self) -> None:
        result: ProcessingResult = {
            "success": True,
            "order_id": "12345",
            "result_data": {"status": "completed"},
            "error_message": None,
        }
        assert result["success"] is True
        assert result["order_id"] == "12345"
        assert result["result_data"] == {"status": "completed"}
        assert result["error_message"] is None

    def test_error_case(self) -> None:
        result: ProcessingResult = {
            "success": False,
            "order_id": "42",
            "result_data": None,
            "error_message": "timeout",
        }
        assert result["success"] is False
        assert result["error_message"] == "timeout"

    def test_is_plain_dict(self) -> None:
        result: ProcessingResult = {
            "success": True,
            "order_id": "1",
            "result_data": None,
            "error_message": None,
        }
        assert isinstance(result, dict)

    def test_access_by_key(self) -> None:
        result: ProcessingResult = {
            "success": True,
            "order_id": "99",
            "result_data": {"foo": "bar"},
            "error_message": None,
        }
        assert result.get("success") is True
        assert result.get("nonexistent", "default") == "default"

    def test_all_exported(self) -> None:
        from src.backend.workflows import dicts as dicts_module

        assert dicts_module.__all__ == ("ProcessingResult",)
