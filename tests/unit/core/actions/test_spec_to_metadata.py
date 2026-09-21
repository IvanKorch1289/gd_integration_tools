"""Unit tests for src.backend.core.actions.spec_to_metadata."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.core.actions.spec_to_metadata import (
    _coerce_tuple,
    _infer_idempotent,
    _infer_side_effect,
    action_spec_to_metadata,
)
from src.backend.core.interfaces.action_dispatcher import ActionMetadata


class TestCoerceTuple:
    def test_none(self) -> None:
        assert _coerce_tuple(None) == ()

    def test_list(self) -> None:
        assert _coerce_tuple(["a", "b"]) == ("a", "b")

    def test_tuple(self) -> None:
        assert _coerce_tuple(("a",)) == ("a",)


class TestInferSideEffect:
    def test_none(self) -> None:
        assert _infer_side_effect(None) == "none"

    def test_get(self) -> None:
        assert _infer_side_effect("GET") == "read"

    def test_post(self) -> None:
        assert _infer_side_effect("POST") == "write"


class TestInferIdempotent:
    def test_none(self) -> None:
        assert _infer_idempotent(None) is False

    def test_get(self) -> None:
        assert _infer_idempotent("GET") is True

    def test_post(self) -> None:
        assert _infer_idempotent("POST") is False


class TestActionSpecToMetadata:
    def test_minimal(self) -> None:
        spec = SimpleNamespace(name="act1")
        meta = action_spec_to_metadata(spec)
        assert isinstance(meta, ActionMetadata)
        assert meta.action == "act1"
        assert meta.description == ""
        assert meta.transports == ("http",)
        assert meta.side_effect == "none"
        assert meta.idempotent is False
        assert meta.tags == ()
        assert meta.deprecated is False

    def test_action_id_priority(self) -> None:
        spec = SimpleNamespace(name="act1", action_id="override")
        meta = action_spec_to_metadata(spec)
        assert meta.action == "override"

    def test_input_model_fallback(self) -> None:
        spec = SimpleNamespace(name="act1", query_model="QM")
        meta = action_spec_to_metadata(spec)
        assert meta.input_model == "QM"

        spec2 = SimpleNamespace(name="act1", path_model="PM", query_model="QM")
        meta2 = action_spec_to_metadata(spec2)
        assert meta2.input_model == "PM"

    def test_explicit_side_effect_and_idempotent(self) -> None:
        spec = SimpleNamespace(
            name="act1", method="POST", side_effect="read", idempotent=True
        )
        meta = action_spec_to_metadata(spec)
        assert meta.side_effect == "read"
        assert meta.idempotent is True

    def test_inferred_from_method(self) -> None:
        spec = SimpleNamespace(name="act1", method="GET")
        meta = action_spec_to_metadata(spec)
        assert meta.side_effect == "read"
        assert meta.idempotent is True

    def test_transports_explicit(self) -> None:
        spec = SimpleNamespace(name="act1", transports=["grpc", "http"])
        meta = action_spec_to_metadata(spec)
        assert meta.transports == ("grpc", "http")

    def test_permissions_and_rate_limit(self) -> None:
        spec = SimpleNamespace(
            name="act1",
            permissions=["admin"],
            rate_limit=100,
            timeout_ms=5000,
            deprecated=True,
            since_version="2.0",
        )
        meta = action_spec_to_metadata(spec)
        assert meta.permissions == ("admin",)
        assert meta.rate_limit == 100
        assert meta.timeout_ms == 5000
        assert meta.deprecated is True
        assert meta.since_version == "2.0"

    def test_missing_name_raises(self) -> None:
        spec = SimpleNamespace()
        with pytest.raises(AttributeError):
            action_spec_to_metadata(spec)
