"""Unit tests for src.backend.core.interfaces.sanitization."""

from __future__ import annotations

from src.backend.core.interfaces.sanitization import MaskingEvent, SanitizationResult


class TestMaskingEvent:
    def test_defaults(self) -> None:
        ev = MaskingEvent(type="EMAIL", count=2)
        assert ev.type == "EMAIL"
        assert ev.count == 2
        assert ev.timestamp == 0.0


class TestSanitizationResult:
    def test_defaults(self) -> None:
        res = SanitizationResult(sanitized_text="***")
        assert res.sanitized_text == "***"
        assert res.replacements == {}
        assert res.audit_events == []
        assert res.sanitized == "***"
        assert res._mapping == {}

    def test_restore(self) -> None:
        res = SanitizationResult(
            sanitized_text="Hello <NAME>", replacements={"<NAME>": "World"}
        )
        assert res.restore("Hello <NAME>") == "Hello World"
