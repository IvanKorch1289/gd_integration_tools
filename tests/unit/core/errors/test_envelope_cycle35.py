"""Tests for build_error_envelope helper (cycle 35 A2).

Дополняет существующие tests/unit/core/test_errors.py:
- envelope format consistency across middlewares
- correlation_id propagation from ASGI scope
- error_id generation (uuid4) when not provided
- backward-compat: optional fields gracefully None when missing
"""

from __future__ import annotations

import re

from src.backend.core.errors import build_error_envelope

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class TestBuildErrorEnvelopeBasic:
    """Базовый контракт envelope."""

    def test_envelope_has_required_keys(self) -> None:
        env = build_error_envelope("test_code", "test detail")
        assert set(env.keys()) == {
            "code",
            "detail",
            "error_id",
            "correlation_id",
            "request_id",
        }

    def test_envelope_code_and_detail_preserved(self) -> None:
        env = build_error_envelope("csrf_token_missing", "CSRF token required")
        assert env["code"] == "csrf_token_missing"
        assert env["detail"] == "CSRF token required"


class TestBuildErrorEnvelopeErrorId:
    """error_id — UUID4 или явно переданный."""

    def test_error_id_is_uuid4_format_when_generated(self) -> None:
        env = build_error_envelope("c", "d")
        assert _UUID4_RE.match(env["error_id"]), (
            f"error_id={env['error_id']!r} is not uuid4 format"
        )

    def test_explicit_error_id_is_used(self) -> None:
        env = build_error_envelope("c", "d", error_id="my-custom-id-123")
        assert env["error_id"] == "my-custom-id-123"

    def test_each_call_generates_unique_error_id(self) -> None:
        e1 = build_error_envelope("c", "d")["error_id"]
        e2 = build_error_envelope("c", "d")["error_id"]
        assert e1 != e2


class TestBuildErrorEnvelopeCorrelationId:
    """correlation_id пробрасывается из scope['state']."""

    def test_correlation_id_propagated_from_scope_state(self) -> None:
        scope = {"state": {"correlation_id": "corr-abc-123"}}
        env = build_error_envelope("c", "d", scope=scope)
        assert env["correlation_id"] == "corr-abc-123"

    def test_correlation_id_none_when_scope_missing(self) -> None:
        env = build_error_envelope("c", "d")
        assert env["correlation_id"] is None

    def test_correlation_id_none_when_state_not_dict(self) -> None:
        scope = {"state": "not-a-dict"}
        env = build_error_envelope("c", "d", scope=scope)
        assert env["correlation_id"] is None

    def test_correlation_id_none_when_state_missing_correlation_id(self) -> None:
        scope = {"state": {"other_key": "value"}}
        env = build_error_envelope("c", "d", scope=scope)
        assert env["correlation_id"] is None


class TestBuildErrorEnvelopeRequestId:
    """request_id пробрасывается из scope."""

    def test_request_id_propagated_from_scope(self) -> None:
        scope = {"request_id": "req-xyz-789"}
        env = build_error_envelope("c", "d", scope=scope)
        assert env["request_id"] == "req-xyz-789"

    def test_request_id_none_when_scope_missing(self) -> None:
        env = build_error_envelope("c", "d")
        assert env["request_id"] is None

    def test_request_id_ignores_non_string_values(self) -> None:
        scope = {"request_id": 12345}  # не строка — игнорируется
        env = build_error_envelope("c", "d", scope=scope)
        assert env["request_id"] is None
