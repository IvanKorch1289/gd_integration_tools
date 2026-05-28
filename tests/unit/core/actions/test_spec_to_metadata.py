"""Unit tests for spec_to_metadata converter (core/actions/).

Wave: [tech-debt/coverage].
Covers: action_spec_to_metadata, _coerce_tuple, _infer_side_effect, _infer_idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.backend.core.actions.spec_to_metadata import (
    _coerce_tuple,
    _infer_idempotent,
    _infer_side_effect,
    action_spec_to_metadata,
)


@dataclass
class _MockSpec:
    """Minimal ActionSpec mock with optional fields."""

    name: str
    action_id: str | None = None
    body_model: Any = None
    path_model: Any = None
    query_model: Any = None
    response_model: Any = None
    description: str | None = None
    tags: list[str] | None = None
    transports: list[str] | None = None
    method: str | None = None
    side_effect: str | None = None
    idempotent: bool | None = None
    permissions: list[str] | None = None
    rate_limit: int | None = None
    timeout_ms: int | None = None
    deprecated: bool = False
    since_version: str | None = None


class TestCoerceTuple:
    """Tests for _coerce_tuple helper."""

    def test_none_returns_empty_tuple(self) -> None:
        result = _coerce_tuple(None)
        assert result == ()

    def test_list_returns_tuple(self) -> None:
        result = _coerce_tuple(["a", "b", "c"])
        assert result == ("a", "b", "c")

    def test_tuple_passed_through(self) -> None:
        result = _coerce_tuple(("x", "y"))
        assert result == ("x", "y")


class TestInferSideEffect:
    """Tests for _infer_side_effect helper."""

    def test_none_returns_none(self) -> None:
        assert _infer_side_effect(None) == "none"

    def test_get_is_read(self) -> None:
        assert _infer_side_effect("GET") == "read"

    def test_head_is_read(self) -> None:
        assert _infer_side_effect("HEAD") == "read"

    def test_options_is_read(self) -> None:
        assert _infer_side_effect("OPTIONS") == "read"

    def test_post_is_write(self) -> None:
        assert _infer_side_effect("POST") == "write"

    def test_put_is_write(self) -> None:
        assert _infer_side_effect("PUT") == "write"

    def test_delete_is_write(self) -> None:
        assert _infer_side_effect("DELETE") == "write"

    def test_patch_is_write(self) -> None:
        assert _infer_side_effect("PATCH") == "write"


class TestInferIdempotent:
    """Tests for _infer_idempotent helper."""

    def test_none_returns_false(self) -> None:
        assert _infer_idempotent(None) is False

    def test_get_is_idempotent(self) -> None:
        assert _infer_idempotent("GET") is True

    def test_head_is_idempotent(self) -> None:
        assert _infer_idempotent("HEAD") is True

    def test_options_is_idempotent(self) -> None:
        assert _infer_idempotent("OPTIONS") is True

    def test_put_is_idempotent(self) -> None:
        assert _infer_idempotent("PUT") is True

    def test_delete_is_idempotent(self) -> None:
        assert _infer_idempotent("DELETE") is True

    def test_post_is_not_idempotent(self) -> None:
        assert _infer_idempotent("POST") is False

    def test_patch_is_not_idempotent(self) -> None:
        assert _infer_idempotent("PATCH") is False


class TestActionSpecToMetadata:
    """Tests for action_spec_to_metadata converter."""

    def test_minimal_spec(self) -> None:
        """Minimal spec with only required fields."""
        spec = _MockSpec(name="test.action")
        result = action_spec_to_metadata(spec)

        assert result.action == "test.action"
        assert result.description == ""
        assert result.input_model is None
        assert result.output_model is None
        assert result.transports == ("http",)
        assert result.side_effect == "none"
        assert result.idempotent is False
        assert result.permissions == ()
        assert result.rate_limit is None
        assert result.timeout_ms is None
        assert result.deprecated is False
        assert result.since_version is None
        assert result.tags == ()

    def test_action_id_takes_priority(self) -> None:
        """action_id should take priority over name if present."""
        spec = _MockSpec(name="fallback", action_id="custom.action")
        result = action_spec_to_metadata(spec)

        assert result.action == "custom.action"

    def test_body_model_as_input(self) -> None:
        """body_model should be used as input_model."""
        spec = _MockSpec(name="test", body_model=dict)
        result = action_spec_to_metadata(spec)

        assert result.input_model is dict

    def test_path_model_fallback(self) -> None:
        """path_model used when body_model is absent."""
        spec = _MockSpec(name="test", path_model=list)
        result = action_spec_to_metadata(spec)

        assert result.input_model is list

    def test_query_model_fallback(self) -> None:
        """query_model used when body_model and path_model are absent."""
        spec = _MockSpec(name="test", query_model=tuple)
        result = action_spec_to_metadata(spec)

        assert result.input_model is tuple

    def test_tags_conversion(self) -> None:
        """Tags list should be converted to tuple."""
        spec = _MockSpec(name="test", tags=["tag1", "tag2"])
        result = action_spec_to_metadata(spec)

        assert result.tags == ("tag1", "tag2")

    def test_explicit_transports(self) -> None:
        """Explicit transports list should override default."""
        spec = _MockSpec(name="test", transports=["mq", "grpc"])
        result = action_spec_to_metadata(spec)

        assert result.transports == ("mq", "grpc")

    def test_method_infers_side_effect(self) -> None:
        """side_effect inferred from method when not explicitly set."""
        spec = _MockSpec(name="test", method="POST")
        result = action_spec_to_metadata(spec)

        assert result.side_effect == "write"

    def test_explicit_side_effect_overrides_method(self) -> None:
        """Explicit side_effect should override method inference."""
        spec = _MockSpec(name="test", method="POST", side_effect="read")
        result = action_spec_to_metadata(spec)

        assert result.side_effect == "read"

    def test_method_infers_idempotent(self) -> None:
        """idempotent inferred from method when not explicitly set."""
        spec = _MockSpec(name="test", method="GET")
        result = action_spec_to_metadata(spec)

        assert result.idempotent is True

    def test_explicit_idempotent_overrides_method(self) -> None:
        """Explicit idempotent should override method inference."""
        spec = _MockSpec(name="test", method="POST", idempotent=True)
        result = action_spec_to_metadata(spec)

        assert result.idempotent is True

    def test_permissions_tuple(self) -> None:
        """Permissions list should be converted to tuple."""
        spec = _MockSpec(name="test", permissions=["admin", "user"])
        result = action_spec_to_metadata(spec)

        assert result.permissions == ("admin", "user")

    def test_rate_limit_preserved(self) -> None:
        """rate_limit should be preserved when set."""
        spec = _MockSpec(name="test", rate_limit=100)
        result = action_spec_to_metadata(spec)

        assert result.rate_limit == 100

    def test_timeout_ms_preserved(self) -> None:
        """timeout_ms should be preserved when set."""
        spec = _MockSpec(name="test", timeout_ms=5000)
        result = action_spec_to_metadata(spec)

        assert result.timeout_ms == 5000

    def test_deprecated_flag(self) -> None:
        """deprecated should be converted to bool."""
        spec = _MockSpec(name="test", deprecated=True)
        result = action_spec_to_metadata(spec)

        assert result.deprecated is True

    def test_since_version_preserved(self) -> None:
        """since_version should be preserved when set."""
        spec = _MockSpec(name="test", since_version="1.5.0")
        result = action_spec_to_metadata(spec)

        assert result.since_version == "1.5.0"

    def test_response_model(self) -> None:
        """response_model should be used as output_model."""
        spec = _MockSpec(name="test", response_model=dict)
        result = action_spec_to_metadata(spec)

        assert result.output_model is dict
